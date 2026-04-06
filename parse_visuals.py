#!/usr/bin/env python3
"""
Parse all visual.json files and extract metadata about table and measure usage
"""

import json
import os
import glob
import re
from collections import defaultdict

def extract_visuals_metadata():
    """Parse all visual.json files and extract metadata"""
    
    # Load list of visual files from the JSON file created by PowerShell
    visual_files_list_path = os.path.join(os.getcwd(), "visual_files_list.json")
    
    if not os.path.exists(visual_files_list_path):
        print(f"ERROR: Visual files list not found: {visual_files_list_path}")
        return [], {}, {}
    
    with open(visual_files_list_path, 'r', encoding='utf-8') as f:
        visual_files_json = json.load(f)
    
    # Handle both single file and array
    if isinstance(visual_files_json, str):
        visual_files = [visual_files_json]
    else:
        visual_files = visual_files_json
    
    print(f"Found {len(visual_files)} visual.json files\n")
    
    # Get all JSON files recursively
    report_structure = defaultdict(lambda: {"pages": defaultdict(list)})
    table_to_visuals = defaultdict(list)
    all_visuals = []
    
    for visual_file in sorted(visual_files):
        try:
            with open(visual_file, 'r', encoding='utf-8') as f:
                visual_data = json.load(f)
           
            # Extract visual info
            visual_id = visual_data.get('name', 'unknown')
            visual_type = visual_data.get('visual', {}).get('visualType', 'unknown')
            
            # Extract title
            title = "Untitled"
            try:
                title_obj = visual_data.get('visual', {}).get('visualContainerObjects', {}).get('title', [{}])[0]
                title_expr = title_obj.get('properties', {}).get('text', {}).get('expr', {})
                if 'Literal' in title_expr:
                    title = title_expr['Literal'].get('Value', 'Untitled').strip("'")
            except (IndexError, TypeError, KeyError):
                pass
            
            # Extract report and page from path
            path_parts = visual_file.split(os.sep)
            report_name = "unknown"
            page_id = "unknown"
            
            for i, part in enumerate(path_parts):
                if "Report" in part and "__Report" in part:
                    report_name = part.replace("__Report", "").strip()
                    break
            
            try:
                pages_idx = path_parts.index("pages")
                if pages_idx + 1 < len(path_parts):
                    page_id = path_parts[pages_idx + 1]
            except ValueError:
                pass
            
            # Extract referenced entities and fields
            referenced_tables = set()
            referenced_fields = set()
            
            def extract_entities(obj, depth=0):
                if depth > 10:  # Prevent infinite recursion
                    return
                if not isinstance(obj, dict):
                    return
                
                # Look for SourceRef with Entity
                if 'SourceRef' in obj and 'Entity' in obj['SourceRef']:
                    referenced_tables.add(obj['SourceRef']['Entity'])
                
                # Look for Property names (field names)
                if 'Property' in obj:
                    referenced_fields.add(obj['Property'])
                
                # Recurse through dict
                for key, value in obj.items():
                    if isinstance(value, dict):
                        extract_entities(value, depth + 1)
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                extract_entities(item, depth + 1)
            
            extract_entities(visual_data)
            
            # Create visual record
            visual_record = {
                "visual_id": visual_id,
                "visual_type": visual_type,
                "title": title,
                "report": report_name,
                "page_id": page_id,
                "tables": list(referenced_tables),
                "fields": list(referenced_fields),
                "file_path": visual_file.replace(os.getcwd() + os.sep, "").replace("\\", "/")
            }
            
            all_visuals.append(visual_record)
            
            # Map tables to visuals
            for table in referenced_tables:
                table_to_visuals[table].append({
                    "visual_id": visual_id,
                    "visual_type": visual_type,
                    "title": title,
                    "report": report_name,
                    "page_id": page_id,
                    "fields": list(referenced_fields)
                })
            
            # Organize by report and page
            report_structure[report_name]["pages"][page_id].append(visual_record)
            
        except json.JSONDecodeError as e:
            print(f"ERROR: Failed to parse {visual_file}: {e}")
        except Exception as e:
            print(f"ERROR: Processing {visual_file}: {e}")
    
    return all_visuals, table_to_visuals, report_structure

def main():
    print("=" * 80)
    print("PARSING VISUAL.JSON FILES")
    print("=" * 80 + "\n")
    
    all_visuals, table_to_visuals, report_structure = extract_visuals_metadata()
    
    # Create output structure
    output_data = {
        "metadata": {
            "generated_at": "2026-04-05",
            "total_visuals": len(all_visuals),
            "total_reports": len(report_structure),
            "tables_referenced": len(table_to_visuals)
        },
        "visuals": all_visuals,
        "table_to_visuals_mapping": {},
        "reports": {}
    }
    
    # Prepare table_to_visuals_mapping
    for table, visuals in sorted(table_to_visuals.items()):
        output_data["table_to_visuals_mapping"][table] = visuals
    
    # Prepare reports summary
    for report_name, report_data in sorted(report_structure.items()):
        pages_summary = {}
        for page_id, page_visuals in report_data["pages"].items():
            pages_summary[page_id] = {
                "visual_count": len(page_visuals),
                "visuals": [v["visual_id"] for v in page_visuals]
            }
        output_data["reports"][report_name] = {
            "pages": pages_summary,
            "total_visuals": len(all_visuals)
        }
    
    # Save output
    output_file = "fabric_visuals_metadata.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\n{'='*80}")
    print("COMPREHENSIVE VISUALS METADATA CREATED")
    print(f"{'='*80}")
    print(f"Saved to: {output_file}")
    print(f"\nSummary:")
    print(f"  - Total Visuals: {output_data['metadata']['total_visuals']}")
    print(f"  - Total Reports: {output_data['metadata']['total_reports']}")
    print(f"  - Unique Tables Referenced: {output_data['metadata']['tables_referenced']}")
    
    print(f"\nTables Referenced in Visuals:")
    for table in sorted(table_to_visuals.keys()):
        count = len(table_to_visuals[table])
        print(f"  {table}: {count} visual(s)")
    
    print(f"\nReports:")
    for report_name, report_data in sorted(report_structure.items()):
        total = sum(len(page_visuals) for page_visuals in report_data["pages"].values())
        print(f"  {report_name}: {len(report_data['pages'])} page(s), {total} visual(s)")

if __name__ == "__main__":
    main()
