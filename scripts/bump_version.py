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
            
    # 4. Clean up all old version markers and create the new one
    import glob
    for old_file in glob.glob('v[0-9]*.[0-9]*.[0-9]*'):
        try:
            os.remove(old_file)
            print(f"Removed old version file: {old_file}")
        except OSError:
            pass
            
    with open(new_version, 'w') as f:
        pass
    print(f"Created new version file: {new_version}")

    print(f"\n✅ 升级版本文件及配置完毕: {new_version}")
    print(f"请使用以下命令完成提交和发版 (复制粘贴运行)：")
    print(f"git commit -am 'chore: bump version to {new_version}'")
    print(f"git tag {new_version}")
    print(f"git push origin main && git push origin {new_version}\n")
        
    return old_version, new_version

if __name__ == "__main__":
    bump_version()
