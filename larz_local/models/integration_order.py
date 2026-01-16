from odoo import models, fields, api
from datetime import datetime, timedelta
import requests
import json
import logging

_logger = logging.getLogger(__name__)


class IntegrationOrder(models.Model):
    _name = 'integration.order'
    _description = 'Integration Order'
    _order = 'date desc, id desc'

    name = fields.Char(string='Name', compute='_compute_name', store=True)
    config_id = fields.Many2one('integration.log', string='Integration Configuration', required=True, ondelete='restrict')
    unit_id = fields.Integer(string='Unit ID', related='config_id.unit_id', store=True)
    
    date = fields.Date(string='Date', required=True, default=fields.Date.today, tracking=True)
    sales_amount = fields.Monetary(string='Sales Amount', required=True, currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one('res.currency', string='Currency', default=lambda self: self.env.company.currency_id)
    ref = fields.Char(string='Reference', required=True, tracking=True)
    
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    
    # Track if synced to remote
    is_synced = fields.Boolean(string='Synced', default=False)
    sync_date = fields.Datetime(string='Last Sync Date')

    @api.depends('ref', 'date')
    def _compute_name(self):
        for record in self:
            if record.ref and record.date:
                record.name = f"{record.ref} - {record.date}"
            else:
                record.name = f"Order #{record.id or 'New'}"


    @api.model
    def cron_send_orders_to_api(self):
        """Cron job to send orders less than 1 month old to daily_sales API every 2 hours"""
        # Calculate date 1 month ago
        one_month_ago = fields.Date.today() - timedelta(days=32)
        
        # Find orders that are less than 1 month old
        orders = self.search([
            ('date', '>=', one_month_ago),
        ])
        
        success_count = 0
        fail_count = 0
        
        # API URL
        api_url = "https://gmc-test.odoo.com/api/daily_sales/create"
        
        # Prepare batch payload
        records_data = []
        for order in orders:
            records_data.append({
                "unit_id": order.unit_id,
                "date": str(order.date),
                "sales_amount": order.sales_amount,
                "ref": order.ref,
            })
        
        if not records_data:
            _logger.info("Cron: No orders to sync (less than 1 month old)")
            return
        
        # Send batch request
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "records": records_data
            },
        }
        
        try:
            response = requests.post(
                api_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
            )
            response.raise_for_status()
            
            result = response.json()
            if result.get('result', {}).get('success'):
                # Mark all orders as synced
                orders.write({
                    'is_synced': True,
                    'sync_date': fields.Datetime.now()
                })
                _logger.info(f"Cron: Successfully synced {len(orders)} orders to API")
            else:
                _logger.warning(f"Cron: API returned error: {result}")
                
        except Exception as e:
            _logger.error(f"Cron: Failed to sync orders to API: {str(e)}")