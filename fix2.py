with open('dashboard.py', 'r', encoding='utf-8') as f:
    c = f.read()

old = 'return render_template_string(BASE_HTML, content=content, logged_in=False, page="")'
new = 'from flask import Markup\n        return render_template_string(BASE_HTML, content=Markup(content), logged_in=False, page="")'

if old in c:
    c = c.replace(old, new)
    with open('dashboard.py', 'w', encoding='utf-8') as f:
        f.write(c)
    print('Done! Applied.')
else:
    print('WARNING: Not found.')