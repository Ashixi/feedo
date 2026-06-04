import re

def clean_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        # Remove single line comments that are not doc comments
        if re.match(r'^\s*//(?!\/|\!).*$', line):
            continue
        
        # Clean up println messages
        if 'println!("' in line:
            # Remove "..."
            line = line.replace('...', '')
            # Remove "!" inside the string
            # we need to be careful not to replace println!
            line = re.sub(r'(println!\(".*?)(!)(.*?"\s*[,)])', r'\1\3', line)
            
            # Remove "успішно", "успішне"
            line = line.replace(' успішно ', ' ')
            line = line.replace(' успішно', '')
            line = line.replace(' успішне', '')
            line = line.replace('успішно ', '')
            
            # Clean specific long messages
            line = line.replace('Запуск Feedo Core (Erasure Coding DHT + Sled Persistent Node)', 'Запуск Feedo Core')
            
            # Capitalize after removing words if needed, or just remove double spaces
            line = line.replace('  ', ' ')
            
        new_lines.append(line)
        
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

clean_file('feedo/feedo-core/src/main.rs')
