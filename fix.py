import re 
f = open('dashboard.py', 'r', encoding='utf-8') 
content = f.read() 
f.close() 
content = content.replace('def register_dashboard(flask_app, secret_key="secret", password="admin1234"):', 'def register_dashboard(flask_app, secret_key="secret", password="admin1234", super_admin_ids=None):\n    super_admin_ids = list(super_admin_ids or [])') 
f = open('dashboard.py', 'w', encoding='utf-8') 
f.write(content) 
f.close() 
print('Done!') 
