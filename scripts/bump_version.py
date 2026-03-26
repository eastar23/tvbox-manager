import os
import re

def bump_version():
    app_file = 'app.py'
    readme_file = 'README.md'
    
    # 1. Read current version from app.py
    with open(app_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    match = re.search(r'APP_VERSION = "v(\d+)\.(\d+)\.(\d+)"', content)
    if not match:
        print("Could not find version in app.py")
        return
    
    major, minor, patch = map(int, match.groups())
    old_version = f"v{major}.{minor}.{patch}"
    new_version = f"v{major}.{minor}.{patch + 1}"
    
    print(f"Bumping version: {old_version} -> {new_version}")
    
    # 2. Update app.py
    new_content = content.replace(f'APP_VERSION = "{old_version}"', f'APP_VERSION = "{new_version}"')
    with open(app_file, 'w', encoding='utf-8') as f:
        f.write(new_content)
        
    # 3. Update README.md
    if os.path.exists(readme_file):
        with open(readme_file, 'r', encoding='utf-8') as f:
            readme_content = f.read()
        new_readme = readme_content.replace(f'({old_version})', f'({new_version})')
        with open(readme_file, 'w', encoding='utf-8') as f:
            f.write(new_readme)
            
    # 4. Update file marker
    if os.path.exists(old_version):
        os.remove(old_version)
    with open(new_version, 'w') as f:
        pass
        
    return old_version, new_version

if __name__ == "__main__":
    bump_version()
