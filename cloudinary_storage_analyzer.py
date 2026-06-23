import os
import cloudinary
from cloudinary.api import resources
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

def get_image_size(bytes_size):
    """Convert bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"

def analyze_cloudinary_storage():
    """Analyze Cloudinary storage for images"""
    print("Fetching images from Cloudinary...")
    
    all_resources = []
    next_cursor = None
    max_results = 500
    
    with tqdm(desc="Fetching resources", unit="batch") as pbar:
        while True:
            try:
                result = resources(
                    resource_type='image',
                    max_results=max_results,
                    next_cursor=next_cursor
                )
                
                all_resources.extend(result.get('resources', []))
                pbar.update(1)
                
                next_cursor = result.get('next_cursor')
                if not next_cursor:
                    break
                    
            except Exception as e:
                print(f"\nError fetching resources: {e}")
                break
    
    total_images = len(all_resources)
    total_bytes = 0
    image_details = []
    
    print(f"\nAnalyzing {total_images} images...")
    
    for resource in tqdm(all_resources, desc="Processing images"):
        bytes_size = resource.get('bytes', 0)
        total_bytes += bytes_size
        
        image_details.append({
            'public_id': resource.get('public_id'),
            'format': resource.get('format'),
            'size_bytes': bytes_size,
            'size_human': get_image_size(bytes_size),
            'url': resource.get('secure_url'),
            'created_at': resource.get('created_at')
        })
    
    # Sort by size (largest first)
    image_details.sort(key=lambda x: x['size_bytes'], reverse=True)
    
    # Print summary
    print("\n" + "="*60)
    print("CLOUDINARY STORAGE ANALYSIS SUMMARY")
    print("="*60)
    print(f"Total Images: {total_images}")
    print(f"Total Storage Used: {get_image_size(total_bytes)}")
    print(f"Total Storage Used (bytes): {total_bytes:,}")
    print("="*60)
    
    # Print size distribution
    print("\nSIZE DISTRIBUTION:")
    size_ranges = [
        (0, 100*1024, "< 100 KB"),
        (100*1024, 1*1024*1024, "100 KB - 1 MB"),
        (1*1024*1024, 10*1024*1024, "1 MB - 10 MB"),
        (10*1024*1024, 100*1024*1024, "10 MB - 100 MB"),
        (100*1024*1024, 1*1024*1024*1024, "100 MB - 1 GB"),
        (1*1024*1024*1024, float('inf'), "> 1 GB")
    ]
    
    for min_size, max_size, label in size_ranges:
        count = sum(1 for img in image_details if min_size <= img['size_bytes'] < max_size)
        percentage = (count / total_images * 100) if total_images > 0 else 0
        print(f"{label:20s}: {count:5d} images ({percentage:5.1f}%)")
    
    # Print top 10 largest images
    print("\nTOP 10 LARGEST IMAGES:")
    print("-" * 60)
    for i, img in enumerate(image_details[:10], 1):
        print(f"{i:2d}. {img['public_id'][:50]:50s}")
        print(f"    Format: {img['format']:5s} | Size: {img['size_human']:10s}")
        print(f"    URL: {img['url']}")
        print()
    
    # Print smallest 10 images
    print("\nTOP 10 SMALLEST IMAGES:")
    print("-" * 60)
    for i, img in enumerate(image_details[-10:], 1):
        print(f"{i:2d}. {img['public_id'][:50]:50s}")
        print(f"    Format: {img['format']:5s} | Size: {img['size_human']:10s}")
        print()
    
    # Save detailed report to file
    output_file = 'cloudinary_storage_report.txt'
    with open(output_file, 'w') as f:
        f.write("CLOUDINARY STORAGE DETAILED REPORT\n")
        f.write("="*60 + "\n\n")
        f.write(f"Total Images: {total_images}\n")
        f.write(f"Total Storage Used: {get_image_size(total_bytes)}\n")
        f.write(f"Total Storage Used (bytes): {total_bytes:,}\n\n")
        
        f.write("ALL IMAGES (sorted by size):\n")
        f.write("-"*60 + "\n")
        for i, img in enumerate(image_details, 1):
            f.write(f"{i:5d}. {img['public_id']}\n")
            f.write(f"      Format: {img['format']} | Size: {img['size_human']} ({img['size_bytes']} bytes)\n")
            f.write(f"      URL: {img['url']}\n")
            f.write(f"      Created: {img['created_at']}\n\n")
    
    print(f"\nDetailed report saved to: {output_file}")
    
    return {
        'total_images': total_images,
        'total_bytes': total_bytes,
        'total_size_human': get_image_size(total_bytes),
        'image_details': image_details
    }

if __name__ == "__main__":
    try:
        results = analyze_cloudinary_storage()
        print("\nAnalysis completed successfully!")
    except Exception as e:
        print(f"\nError: {e}")
        print("Make sure your .env file contains:")
        print("  CLOUDINARY_CLOUD_NAME")
        print("  CLOUDINARY_API_KEY")
        print("  CLOUDINARY_API_SECRET")
