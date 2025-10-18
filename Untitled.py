with open(".gitignore", "w") as f:
    f.write("""# === Python cache ===
__pycache__/
*.py[cod]
*$py.class

# === Virtual environment ===
venv/
.env/
.env

# === IDE / Edytory ===
.vscode/
.idea/
*.code-workspace

# === Logi i tymczasowe ===
*.log
*.tmp
*.bak

# === Systemowe ===
.DS_Store
Thumbs.db

# === Plik z sekretami ===
secrets.py

# === Pliki bazy danych lokalnej ===
*.sqlite3
""")
print("Plik .gitignore został utworzony!")
