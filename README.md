how to setup in your local

```
python --version
python -m .venv venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
python main.py
```
.env template
```
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Later you can add these when you wire up Odoo for real:
ODOO_URL=https://your-odoo-instance.com
ODOO_DB=your_db
ODOO_USERNAME=your_username
ODOO_PASSWORD=your_password
```
