# from config import Coverage_filename_origin
# from config import Coverage_filename_later
import re
import os



def get_line_content_with_context(file_path, line_number, context_lines=6):
    """
    Get the contents of the specified line number in the file and its context
    
    parameter:
        file_path (str): file path
        line_number (int): line number (starting from 1)
        context_lines (int): Number of context lines, default is 5
    
    return:
        dict: {
            'target_line': target line content,
            'target_line_number': target line number,
            'before': list of previous lines,
            'after': the content list of the next few lines,
            'full_context': full context content
        }
        Return None on error
    """
    try:
        with open(file_path, 'r') as f:
            lines = [line.rstrip() for line in f.readlines()]
        
        # Check if the line number is valid
        if line_number < 1 or line_number > len(lines):
            return None
        
        # Compute context scope
        start_line = max(1, line_number - context_lines)
        end_line = min(len(lines), line_number + context_lines)
        
        # Extract content
        result = {
            'target_line': lines[line_number-1],
            'target_line_number': line_number,
            'before': lines[start_line-1 : line_number-1],
            'after': lines[line_number : end_line],
            'full_context': lines[start_line-1 : end_line],
            'start_line': start_line,
            'end_line': end_line
        }
        
        return result
        
    except Exception as e:
        print(f"读取文件出错: {e}")
        return None


def find_file_path(filename, search_dir='.'):
    """
    Recursively search for files in the specified directory
    
    parameter:
        filename (str): the file name to find (such as FPU.scala)
        search_dir (str): root directory to search, defaults to the current directory
    
    return:
        str: the full path of the file, returns None if not found
    """
    for root, dirs, files in os.walk(search_dir):
        if filename in files:
            return os.path.join(root, filename)
    return None


def get_line_content(file_path, line_number):
    try:
        with open(file_path, 'rb') as f:
            # Read by byte to avoid encoding interference
            for i, line in enumerate(f, 1):
                if i == line_number:
                    return line.decode('utf-8').strip()
        return None
    except Exception as e:
        print(f"Error: {str(e)}")
        return None


def extract_lines_with_prefix_origin(module_name, Coverage_filename_origin, prefix="%000000"):
    """
    Extracts all lines of code containing a specific prefix from a specified Verilog module.
    
    parameter:
        module_name (str): module name to be extracted
        prefix (str): The prefix to match, default is "%000000"
    
    return:
        list: list containing matching lines (leading and trailing spaces removed)
    """
    try:
        with open(Coverage_filename_origin, "r") as file:
            verilog_code = file.read()
    except FileNotFoundError:
        print(f"错误：文件 '{Coverage_filename_origin}' 未找到。")
        return []
    except IOError:
        print(f"错误：读取文件 '{Coverage_filename_origin}' 时发生IO错误。")
        return []
    
    lines = verilog_code.splitlines()
    current_module = None
    in_target_module = False
    matched_lines = []
    file_infos = []
    line_numbers = []

    for line in lines:
        stripped_line = line.strip()
        
        # Check module start (use strip() to avoid leading spaces)
        if stripped_line.startswith("module"):
            # Extract module name: process "module <name>" format, ignore parameter list [1] (@ref)
            parts = stripped_line.split()
            if len(parts) >= 2:
                current_module = parts[1].split("(")[0]  # Handle possible parameter lists
                if current_module == module_name:
                    in_target_module = True
                else:
                    in_target_module = False
            else:
                current_module = None
        
        # If not in the target module, skip the current line
        if not in_target_module:
            continue
        
        # In the target module, check if the line contains prefix [1](@ref)
        if prefix in stripped_line:
            # Filter out all printing-related code lines (to avoid page freezes caused by a large number of $fwrite statements)
            if ('PRINTF_COND' in stripped_line or 
                '$fwrite' in stripped_line or
                'io_timer' in stripped_line):  # io_timer is usually a parameter of $fwrite
                continue  # Skip printing related lines
            
            matched_lines.append(stripped_line)  # Store a whitespace-removed version to keep things tidy
            file_info = "000000"  # default value
            line_number = "000000"
            filename = " "
            codeline = " "
            codeline_context = " "
            codeline_context_list = []
            # Extract file name and line number
            file_match = re.search(r'@\[([^ ]+) (\d+):\d+\]', stripped_line)
            if file_match:
                file_info = file_match.group(1).strip()
                filename = find_file_path(file_info,"/root/DAC26/test/rocket-chip")
                           
                
                line_number = file_match.group(2)
                # line_number = 303

                # # print(filename)
                # print(line_number)
                # print(filename)
                codeline = get_line_content(filename, int(line_number))
                codeline_context = get_line_content_with_context(filename, int(line_number))
                # print(codeline)
                #print(codeline_context)
                # exit()
            
            file_infos.append(filename)
            line_numbers.append(codeline)
            #codeline_context_list.append(codeline_context)
            
            
        
        # Check module end
        if stripped_line.startswith("endmodule"):
            if in_target_module:
                break  # The target module ends and exits the loop
            in_target_module = False
    
    
    return matched_lines ,file_infos, line_numbers#, codeline_context_list



def extract_lines_with_prefix_stage(module_name, Coverage_filename_later, prefix="%000000"):
    """
    Extracts all lines of code containing a specific prefix from a specified Verilog module.
    
    parameter:
        module_name (str): module name to be extracted
        prefix (str): The prefix to match, default is "%000000"
    
    return:
        list: list containing matching lines (leading and trailing spaces removed)
    """
    Coverage_filename_later = Coverage_filename_later
    try:
        with open(Coverage_filename_later, "r") as file:
            verilog_code = file.read()
    except FileNotFoundError:
        print(f"错误：文件 '{Coverage_filename_later}' 未找到。")
        return []
    except IOError:
        print(f"错误：读取文件 '{Coverage_filename_later}' 时发生IO错误。")
        return []
    
    lines = verilog_code.splitlines()
    current_module = None
    in_target_module = False
    matched_lines = []

    for line in lines:
        stripped_line = line.strip()
        
        # Check module start (use strip() to avoid leading spaces)
        if stripped_line.startswith("module"):
            # Extract module name: process "module <name>" format, ignore parameter list [1] (@ref)
            parts = stripped_line.split()
            if len(parts) >= 2:
                current_module = parts[1].split("(")[0]  # Handle possible parameter lists
                if current_module == module_name:
                    in_target_module = True
                else:
                    in_target_module = False
            else:
                current_module = None
        
        # If not in the target module, skip the current line
        if not in_target_module:
            continue
        
        # In the target module, check if the line contains prefix [1](@ref)
        if prefix in stripped_line:
            # Filter out all printing-related code lines (to avoid page freezes caused by a large number of $fwrite statements)
            if ('PRINTF_COND' in stripped_line or 
                '$fwrite' in stripped_line or
                'io_timer' in stripped_line):  # io_timer is usually a parameter of $fwrite
                continue  # Skip printing related lines
            
            matched_lines.append(stripped_line)  # Store a whitespace-removed version to keep things tidy
        
        # Check module end
        if stripped_line.startswith("endmodule"):
            if in_target_module:
                break  # The target module ends and exits the loop
            in_target_module = False
    
    return matched_lines
