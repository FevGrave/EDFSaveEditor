import os
import re
import pkg_resources
import ast
import sys
from pathlib import Path

def get_installed_packages():
    """Get a dictionary of installed packages and their versions."""
    return {pkg.key: pkg.version for pkg in pkg_resources.working_set}

def find_imports(file_path):
    """Extract import statements from a Python file."""
    imports = set()
    
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            tree = ast.parse(file.read(), filename=file_path)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    if name.name.split('.')[0]:  # Get base package name
                        imports.add(name.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])
                    
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"Error parsing {file_path}: {e}")
    
    return imports

def scan_project(directory):
    """Scan project directory for Python files and collect imports."""
    all_imports = set()
    directory = Path(directory)
    
    # Walk through directory
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                imports = find_imports(file_path)
                all_imports.update(imports)
    
    return all_imports

def create_requirements_file(directory, output_file='requirements.txt', include_versions=True):
    """Create a requirements.txt file based on project imports."""
    # Get installed packages
    installed_packages = get_installed_packages()
    
    # Scan project for imports
    project_imports = scan_project(directory)
    
    # Filter imports that match installed packages
    requirements = []
    for pkg in project_imports:
        # Convert package name to pip-compatible format
        pkg_name = pkg.replace('_', '-').lower()
        if pkg_name in installed_packages:
            if include_versions:
                requirements.append(f"{pkg_name}=={installed_packages[pkg_name]}")
            else:
                requirements.append(pkg_name)
    
    # Write requirements to file
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            for req in sorted(requirements):
                f.write(f"{req}\n")
        print(f"Successfully created {output_file} with {len(requirements)} packages")
    except Exception as e:
        print(f"Error writing requirements file: {e}")
    
    return requirements

def main():
    """Main function to run the requirements file generator."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate a requirements.txt file from project imports.')
    parser.add_argument('directory', nargs='?', default='.', 
                       help='Project directory to scan (default: current directory)')
    parser.add_argument('--output', '-o', default='requirements.txt',
                       help='Output file name (default: requirements.txt)')
    parser.add_argument('--no-versions', action='store_false', dest='include_versions',
                       help='Exclude version numbers from requirements')
    
    args = parser.parse_args()
    
    # Validate directory
    if not os.path.isdir(args.directory):
        print(f"Error: {args.directory} is not a valid directory")
        sys.exit(1)
    
    create_requirements_file(
        directory=args.directory,
        output_file=args.output,
        include_versions=args.include_versions
    )

if __name__ == '__main__':
    main()