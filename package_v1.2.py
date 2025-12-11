import shutil
import os
import time

def package():
    dist_dir = "dist"
    target_dir = "RallyETA_Portable_v1.2"
    zip_name = "RallyETA_Portable_v1.2"
    
    # Remove existing target if any
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
        print(f"Removed existing {target_dir}")
        
    # Remove existing zip if any
    if os.path.exists(zip_name + ".zip"):
        os.remove(zip_name + ".zip")
        print(f"Removed existing {zip_name}.zip")
    
    # Rename dist to target
    # Copying is safer in case we need dist again
    print(f"Copying {dist_dir} to {target_dir}...")
    shutil.copytree(dist_dir, target_dir)
    
    # Zip
    print(f"Zipping {target_dir}...")
    shutil.make_archive(zip_name, 'zip', root_dir='.', base_dir=target_dir)
    print(f"Created {zip_name}.zip")
    
    # Verify
    if os.path.exists(zip_name + ".zip"):
        size_mb = os.path.getsize(zip_name + ".zip") / (1024*1024)
        print(f"Zip size: {size_mb:.2f} MB")

if __name__ == "__main__":
    package()
