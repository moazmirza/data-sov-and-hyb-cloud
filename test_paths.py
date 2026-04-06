from pathlib import Path
import os

root = Path.cwd()
print(f"Working dir: {root}")

# Try direct access
model_path = root / "shared" / "fabric-ext_fabric_space_moaz" / "semantic-models" / "semantic_model_purview_dataproduct_residency_gold__SemanticModel"
print(f"\nModel path: {model_path}")
print(f"Model exists: {model_path.exists()}")
print(f"Model is_dir: {model_path.is_dir()}")
print(f"Model is_symlink: {model_path.is_symlink()}")

if model_path.exists():
    # Try os.listdir instead
    try:
        print(f"os.listdir Model contents:")
        items = os.listdir(str(model_path))
        for item in items:
            print(f"  {item}")
            
        # Look for definition directory
        definition_parent = model_path / "definition"
        print(f"\nDefinition path: {definition_parent}")
        print(f"Definition exists: {definition_parent.exists()}")
        
        if definition_parent.exists():
            definition_path = definition_parent / "definition"
            print(f"Definition/definition path: {definition_path}")
            print(f"Definition/definition exists: {definition_path.exists()}")
            
            if definition_path.exists():
                tables_path = definition_path / "tables"
                print(f"Tables path: {tables_path}")
                print(f"Tables exists: {tables_path.exists()}")
                
                if tables_path.exists():
                    tmdl_files = list(tables_path.glob("*.tmdl"))
                    print(f"Tables contents ({len(tmdl_files)} files):")
                    for f in tmdl_files[:5]:
                        print(f"  {f.name}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
