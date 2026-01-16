{
    'name': 'Integration Data Receiver',
    'version': '17.0.1.0.0',
    'summary': 'Receives data from Integration Configuration API and logs it',
    'description': 'Module to fetch integration configuration data from mall_management API and log the records.',
    'author': 'ahmed hamdy',
    'category': 'Tools',
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
        'views/integration_log_views.xml',
        'views/integration_order_views.xml',
        'data/cron_data.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
