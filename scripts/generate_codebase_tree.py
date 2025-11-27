#!/usr/bin/env python3
import os
from pathlib import Path

def should_ignore(path_str, name):
    ignore_patterns = [
        '__pycache__',
        '.pyc',
        '.git',
        'venv',
        'node_modules',
        '.pytest_cache',
        '.mypy_cache',
        'test-results',
        '.env',
        '.DS_Store',
        'site-packages',
        'lib/python',
        'include/python',
        'bin/',
        'pyvenv.cfg'
    ]
    
    if any(pattern in path_str or pattern in name for pattern in ignore_patterns):
        return True
    
    if name.startswith('.'):
        return True
    
    return False

def generate_tree(root_dir, prefix="", is_last=True, max_depth=3, current_depth=0):
    root_path = Path(root_dir)
    if not root_path.exists():
        return []
    
    items = sorted([item for item in root_path.iterdir() if not should_ignore(str(item), item.name)])
    
    tree_lines = []
    
    for i, item in enumerate(items):
        is_last_item = (i == len(items) - 1)
        current_prefix = "└── " if is_last_item else "├── "
        
        if item.is_dir():
            tree_lines.append(f"{prefix}{current_prefix}{item.name}/")
            extension = "    " if is_last_item else "│   "
            if current_depth < max_depth:
                sub_tree = generate_tree(
                    item, 
                    prefix + extension, 
                    is_last_item, 
                    max_depth, 
                    current_depth + 1
                )
                tree_lines.extend(sub_tree)
        else:
            tree_lines.append(f"{prefix}{current_prefix}{item.name}")
    
    return tree_lines

def main():
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    print("Generating codebase tree...")
    tree_lines = generate_tree(project_root, max_depth=4)
    
    tree_output = "\n".join(tree_lines)
    print("\n" + tree_output)
    
    return tree_output

if __name__ == "__main__":
    main()

