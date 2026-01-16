from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import logging
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# pyodbc is optional - only needed for SQL Anywhere connection
try:
    import pyodbc
    PYODBC_AVAILABLE = True
except ImportError:
    pyodbc = None
    PYODBC_AVAILABLE = False


_logger = logging.getLogger(__name__)


class IntegrationLog(models.Model):
    _name = 'integration.log'
    _description = 'Integration Configuration Log'
    _order = 'fetch_date desc, id desc'

    name = fields.Char(string='Name', compute='_compute_name', store=True)
    fetch_date = fields.Datetime(string='Fetch Date', default=fields.Datetime.now, readonly=True)
    
    # Fields from API response
    config_id = fields.Integer(string='Config ID', readonly=True)
    unit_id = fields.Integer(string='Unit ID', readonly=True)
    unit_name = fields.Char(string='Unit Name', readonly=True)
    driver = fields.Char(string='Driver', readonly=True)
    host = fields.Char(string='Host', readonly=True)
    server_name = fields.Char(string='Server Name', readonly=True)
    database = fields.Char(string='Database', readonly=True)
    table_name = fields.Char(string='Table Name', readonly=True)
    uid = fields.Char(string='UID', readonly=True)
    pwd = fields.Char(string='PWD', readonly=True)
    date = fields.Char(string='Date Field', readonly=True)
    amount = fields.Char(string='Amount Field', readonly=True)
    ref = fields.Char(string='Reference', readonly=True)
    
    # API Configuration
    error_message = fields.Text(string='Error Message', readonly=True)



    def fetch_data_from_sql(self):
        """Fetch data from SQL database using dynamic column names from Odoo fields"""
        conn_str = (
            f"DRIVER={self.driver};"
            f"HOST={self.host};"
            f"ServerName={self.server_name};"
            f"DATABASE={self.database};"
            f"UID={self.uid};"
            f"PWD={self.pwd};"
        )

        # Get column names from Odoo fields
        ref_column = self.ref  # اسم الكولوم للـ Reference
        date_column = self.date  # اسم الكولوم للـ Date
        amount_column = self.amount  # اسم الكولوم للـ Amount

        query = f"SELECT {ref_column}, {date_column}, {amount_column} FROM DBA.{self.table_name}"

        try:
            conn = pyodbc.connect(conn_str)
            cursor = conn.cursor()
            cursor.execute(query)
            
            # Get column names from cursor description
            columns = [column[0] for column in cursor.description]
            records = cursor.fetchall()

            for row in records:
                # Convert row to dictionary using column names
                row_dict = dict(zip(columns, row))
                
                ref_value = row_dict.get(ref_column)
                date_value = row_dict.get(date_column)
                amount_value = row_dict.get(amount_column) or 0.0

                # Create order record in integration.order model
                existing_check = self.env['integration.order'].search([
                    ('ref', '=', ref_value),
                    ('date', '=', date_value),
                    ('config_id', '=', self.id)
                ], limit=1)

                if existing_check:
                    old_amount = existing_check.sales_amount or 0.0
                    if float(amount_value) > old_amount:
                        existing_check.write({
                            'ref': ref_value,
                            'date': date_value,
                            'sales_amount': float(amount_value),
                        })
                    continue

                self.env['integration.order'].create({
                    'config_id': self.id,
                    'ref': ref_value,
                    'date': date_value,
                    'sales_amount': float(amount_value),
                })

            cursor.close()
            conn.close()
        except Exception as e:
            raise Warning(f"خطأ في الاتصال بقاعدة البيانات: {e}")


    @api.depends('unit_name', 'fetch_date')
    def _compute_name(self):
        for record in self:
            if record.unit_name and record.fetch_date:
                record.name = f"{record.unit_name} - {record.fetch_date.strftime('%Y-%m-%d %H:%M')}"
            else:
                record.name = f"Log #{record.id or 'New'}"

    def action_fetch_data(self):
        """Fetch data from the Integration Configuration API"""
        self.ensure_one()
        try:
            url = 'https://gmc-test.odoo.com/api/integration_config/get'
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('data'):
                for config in data['data']:
                    existing_record = self.search([('config_id', '=', config.get('id'))])
                    if not existing_record:
                        self.create({
                        'fetch_date': fields.Datetime.now(),
                        'config_id': config.get('id'),
                        'unit_id': config.get('unit_id'),
                        'unit_name': config.get('unit_name'),
                        'driver': config.get('driver'),
                        'host': config.get('host'),
                        'server_name': config.get('server_name'),
                        'database': config.get('database'),
                        'uid': config.get('uid'),
                        'pwd': config.get('pwd'),
                        'date': config.get('date'),
                        'amount': config.get('amount'),
                        'ref': config.get('ref'),
                        'table_name': config.get('table_name'),
                    })
                    else:
                        existing_record.write({
                            'fetch_date': fields.Datetime.now(),
                            'unit_id': config.get('unit_id'),
                            'unit_name': config.get('unit_name'),
                            'driver': config.get('driver'),
                            'host': config.get('host'),
                            'server_name': config.get('server_name'),
                            'database': config.get('database'),
                            'uid': config.get('uid'),
                            'pwd': config.get('pwd'),
                            'date': config.get('date'),
                            'amount': config.get('amount'),
                            'ref': config.get('ref'),
                            'table_name': config.get('table_name'),
                        })
                
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            _logger.error(f"Failed to fetch integration configs: {error_msg}")
            raise UserError(_('Failed to fetch data from API: %s') % error_msg)

    @api.model
    def cron_fetch_integration_data(self):
        """Cron job method to automatically fetch data from API every hour"""
        try:
            url = 'https://gmc-test.odoo.com/api/integration_config/get'
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('data'):
                for config in data['data']:
                    existing_record = self.search([('config_id', '=', config.get('id'))])
                    if not existing_record:
                        self.create({
                            'fetch_date': fields.Datetime.now(),
                            'config_id': config.get('id'),
                            'unit_id': config.get('unit_id'),
                            'unit_name': config.get('unit_name'),
                            'driver': config.get('driver'),
                            'host': config.get('host'),
                            'server_name': config.get('server_name'),
                            'database': config.get('database'),
                            'uid': config.get('uid'),
                            'pwd': config.get('pwd'),
                            'date': config.get('date'),
                            'amount': config.get('amount'),
                            'ref': config.get('ref'),
                            'table_name': config.get('table_name'),
                        })
                    else:
                        existing_record.write({
                            'fetch_date': fields.Datetime.now(),
                            'unit_id': config.get('unit_id'),
                            'unit_name': config.get('unit_name'),
                            'driver': config.get('driver'),
                            'host': config.get('host'),
                            'server_name': config.get('server_name'),
                            'database': config.get('database'),
                            'uid': config.get('uid'),
                            'pwd': config.get('pwd'),
                            'date': config.get('date'),
                            'amount': config.get('amount'),
                            'ref': config.get('ref'),
                            'table_name': config.get('table_name'),
                        })
                
                _logger.info(f"Cron: Successfully fetched {len(data['data'])} integration configs")
            else:
                _logger.warning("Cron: API returned no data")
                
        except Exception as e:
            _logger.error(f"Cron: Failed to fetch integration configs: {str(e)}")

    @api.model
    def cron_fetch_data_from_sql(self):
        """Cron job to fetch data from SQL for all integration log records every hour"""
        records = self.search([])
        for record in records:
            try:
                # Check if record has required connection fields
                if record.driver and record.host and record.database and record.table_name:
                    record.fetch_data_from_sql()
                    _logger.info(f"Cron: Successfully fetched SQL data for config {record.id} - {record.unit_name}")
                else:
                    _logger.warning(f"Cron: Skipping config {record.id} - missing connection fields")
            except Exception as e:
                _logger.error(f"Cron: Failed to fetch SQL data for config {record.id}: {str(e)}")