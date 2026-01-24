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

    # Date Configuration (New)
    date_mode = fields.Selection([
        ('single', 'Single Date Column'),
        ('range', 'Open/Close Date Columns')
    ], string='Date Mode', default='single', readonly=True)
    check_open_field = fields.Char(string='Check Open Column', readonly=True)
    check_close_field = fields.Char(string='Check Close Column', readonly=True)





    def fetch_data_from_sql(self):
        """Fetch data from SQL database using dynamic column names from Odoo fields"""
        
        # Build connection string based on driver type
        if 'SQL Server' in self.driver:
            # SQL Server connection string
            conn_str = (
                f"DRIVER={self.driver};"
                f"SERVER={self.host};"
                f"DATABASE={self.database};"
                f"UID={self.uid};"
                f"PWD={self.pwd};"
            )
        else:
            # SQL Anywhere connection string
            conn_str = (
                f"DRIVER={self.driver};"
                f"HOST={self.host};"
                f"ServerName={self.server_name};"
                f"DATABASE={self.database};"
                f"UID={self.uid};"
                f"PWD={self.pwd};"
            )

        # Get column names from Odoo fields
        ref_column = self.ref
        amount_column = self.amount

        # Determine columns to select based on mode
        select_columns = [ref_column, amount_column]
        date_columns = []
        
        if self.date_mode == 'range':
            # In Range Mode, we fetch CheckOpen and CheckClose columns
            check_open_col = self.check_open_field
            check_close_col = self.check_close_field
            if check_open_col:
                select_columns.append(check_open_col)
            if check_close_col:
                select_columns.append(check_close_col)
        else:
            # In Single Mode (Default), we fetch the comma-separated date columns
            date_columns_str = self.date or ''
            date_columns = [d.strip() for d in date_columns_str.split(',') if d.strip()]
            select_columns.extend(date_columns)

        # Construct query
        select_part = ", ".join(select_columns)
        query = f"SELECT {select_part} FROM {self.table_name}"

        try:
            conn = pyodbc.connect(conn_str)
            cursor = conn.cursor()
            cursor.execute(query)
            
            # Get column names from cursor description
            columns = [column[0] for column in cursor.description]
            records = cursor.fetchall()

            for row in records:
                # Convert row to dictionary
                row_dict = dict(zip(columns, row))
                
                ref_value = row_dict.get(ref_column)
                amount_value = row_dict.get(amount_column) or 0.0
                
                # Determine date values based on mode
                date_value = None
                check_open_value = None
                check_close_value = None

                if self.date_mode == 'range':
                    # Range Mode Logic
                    if self.check_open_field:
                        check_open_value = row_dict.get(self.check_open_field)
                    if self.check_close_field:
                        check_close_value = row_dict.get(self.check_close_field)
                    
                    # Primary date is Check Open
                    if check_open_value:
                        date_value = check_open_value.date() if hasattr(check_open_value, 'date') else check_open_value
                    # If check open is missing but check close exists, use check close
                    elif check_close_value:
                        date_value = check_close_value.date() if hasattr(check_close_value, 'date') else check_close_value

                else:
                    # Single Mode Logic (Legacy)
                    for d_col in date_columns:
                        val = row_dict.get(d_col)
                        if val:
                            date_value = val
                            break
                    
                    # IMPORTANT: Removed "if not date_value: continue" to allow missing dates

                # Create or Update order record
                # UPDATED IDENTITY: Search only by 'ref' and 'config_id'
                existing_check = self.env['integration.order'].search([
                    ('ref', '=', ref_value),
                    ('config_id', '=', self.id)
                ], limit=1)

                vals = {
                    'sales_amount': float(amount_value),
                    'date': date_value, 
                    'check_open': check_open_value,
                    'check_close': check_close_value,
                }

                if existing_check:
                    # Update logic: Always update if we have new info or if amount increased
                    # For simplicity and robustness like Kov, we update essential fields
                    existing_check.write(vals)
                else:
                    vals.update({
                        'config_id': self.id,
                        'ref': ref_value,
                    })
                    self.env['integration.order'].create(vals)

            cursor.close()
            conn.close()
        except Exception as e:
            raise UserError(f"خطأ في الاتصال بقاعدة البيانات: {e}")


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
                    vals = {
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
                        'date_mode': config.get('date_mode'),
                        'check_open_field': config.get('check_open_field'),
                        'check_close_field': config.get('check_close_field'),
                    }
                    
                    if not existing_record:
                        vals['config_id'] = config.get('id')
                        self.create(vals)
                    else:
                        existing_record.write(vals)
                
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
                    vals = {
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
                        'date_mode': config.get('date_mode'),
                        'check_open_field': config.get('check_open_field'),
                        'check_close_field': config.get('check_close_field'),
                    }

                    if not existing_record:
                        vals['config_id'] = config.get('id')
                        self.create(vals)
                    else:
                        existing_record.write(vals)
                
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