import json
import os

def parse_other_artists(file_path):
    artists_data = []
    
    # Check if file exists
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return []
        
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Split by the first comma only
        parts = line.split(',', 1)
        
        if len(parts) >= 2:
            artist_name = parts[0].strip()
            album_name = parts[1].strip()
            
            # Check if artist already exists in our list
            existing_artist = next((item for item in artists_data if item["artist"] == artist_name), None)
            
            if existing_artist:
                if album_name not in existing_artist["albums"]:
                    existing_artist["albums"].append(album_name)
            else:
                artists_data.append({
                    "artist": artist_name,
                    "albums": [album_name]
                })
        else:
            # Handle lines without comma if necessary, though instruction says "comma before is artist, after is album"
            print(f"Skipping line (no comma found): {line}")
            
    return artists_data

def main():
    base_dir = r"d:\my_program\Playlist"
    input_path = os.path.join(base_dir, "Other_Artists.txt")
    output_path = os.path.join(base_dir, "other_artists.json")
    
    artists_data = parse_other_artists(input_path)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(artists_data, f, indent=4, ensure_ascii=False)
        
    print(f"Generated {output_path} with {len(artists_data)} artists")

if __name__ == "__main__":
    main()
