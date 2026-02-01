# from config import Coverage_filename_origin
# from config import Coverage_filename_later
import re
import os



def get_line_content_with_context(file_path, line_number, context_lines=6):
    """
    获取文件中指定行号的内容及其上下文
    
    参数:
        file_path (str): 文件路径
        line_number (int): 行号（从1开始）
        context_lines (int): 上下文的行数，默认为5
    
    返回:
        dict: {
            'target_line': 目标行内容,
            'target_line_number': 目标行号,
            'before': 前几行内容列表,
            'after': 后几行内容列表,
            'full_context': 完整上下文内容
        }
        出错返回None
    """
    try:
        with open(file_path, 'r') as f:
            lines = [line.rstrip() for line in f.readlines()]
        
        # 检查行号是否有效
        if line_number < 1 or line_number > len(lines):
            return None
        
        # 计算上下文范围
        start_line = max(1, line_number - context_lines)
        end_line = min(len(lines), line_number + context_lines)
        
        # 提取内容
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


# 缓存 find_file_path 结果，避免同一文件重复 os.walk（未覆盖行数多时卡在开头的根因）
_find_file_path_cache = {}

def find_file_path(filename, search_dir='.'):
    """
    在指定目录下递归查找文件（带缓存，同一 (filename, search_dir) 只 walk 一次）
    
    参数:
        filename (str): 要查找的文件名（如FPU.scala）
        search_dir (str): 搜索的根目录，默认为当前目录
    
    返回:
        str: 文件的完整路径，未找到返回None
    """
    key = (filename, os.path.abspath(search_dir))
    if key not in _find_file_path_cache:
        result = None
        if os.path.exists(search_dir):
            for root, dirs, files in os.walk(search_dir):
                if filename in files:
                    result = os.path.join(root, filename)
                    break
        _find_file_path_cache[key] = result
    return _find_file_path_cache[key]


def get_line_content(file_path, line_number):
    try:
        with open(file_path, 'rb') as f:
            # 按字节读取避免编码干扰
            for i, line in enumerate(f, 1):
                if i == line_number:
                    return line.decode('utf-8').strip()
        return None
    except Exception as e:
        print(f"Error: {str(e)}")
        return None


def extract_lines_with_prefix_origin(module_name, Coverage_filename_origin, prefix="%000000"):
    """
    从指定Verilog模块中提取所有包含特定前缀的代码行。
    
    参数:
        module_name (str): 要提取的模块名称
        prefix (str): 要匹配的前缀，默认为"%000000"
    
    返回:
        list: 包含匹配行的列表（已去除首尾空格）
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
        
        # 检查模块开始（使用strip()避免前导空格影响）
        if stripped_line.startswith("module"):
            # 提取模块名：处理"module <name>"格式，忽略参数列表[1](@ref)
            parts = stripped_line.split()
            if len(parts) >= 2:
                current_module = parts[1].split("(")[0]  # 处理可能存在的参数列表
                if current_module == module_name:
                    in_target_module = True
                else:
                    in_target_module = False
            else:
                current_module = None
        
        # 如果不在目标模块，跳过当前行
        if not in_target_module:
            continue
        
        # 在目标模块中，检查行是否包含前缀[1](@ref)
        if prefix in stripped_line:
            # 过滤掉所有打印相关的代码行（避免大量 $fwrite 语句导致页面卡死）
            if ('PRINTF_COND' in stripped_line or 
                '$fwrite' in stripped_line or
                'io_timer' in stripped_line):  # io_timer 通常是 $fwrite 的参数
                continue  # 跳过打印相关的行
            
            matched_lines.append(stripped_line)  # 存储去除空格的版本以保持整洁
            file_info = "000000"  # 默认值
            line_number = "000000"
            filename = " "
            codeline = " "
            codeline_context = " "
            codeline_context_list = []
            # 提取文件名和行号
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
            
            
        
        # 检查模块结束
        if stripped_line.startswith("endmodule"):
            if in_target_module:
                break  # 目标模块结束，退出循环
            in_target_module = False
    
    
    return matched_lines ,file_infos, line_numbers#, codeline_context_list



def extract_lines_with_prefix_stage(module_name, Coverage_filename_later, prefix="%000000"):
    """
    从指定Verilog模块中提取所有包含特定前缀的代码行。
    
    参数:
        module_name (str): 要提取的模块名称
        prefix (str): 要匹配的前缀，默认为"%000000"
    
    返回:
        list: 包含匹配行的列表（已去除首尾空格）
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
        
        # 检查模块开始（使用strip()避免前导空格影响）
        if stripped_line.startswith("module"):
            # 提取模块名：处理"module <name>"格式，忽略参数列表[1](@ref)
            parts = stripped_line.split()
            if len(parts) >= 2:
                current_module = parts[1].split("(")[0]  # 处理可能存在的参数列表
                if current_module == module_name:
                    in_target_module = True
                else:
                    in_target_module = False
            else:
                current_module = None
        
        # 如果不在目标模块，跳过当前行
        if not in_target_module:
            continue
        
        # 在目标模块中，检查行是否包含前缀[1](@ref)
        if prefix in stripped_line:
            # 过滤掉所有打印相关的代码行（避免大量 $fwrite 语句导致页面卡死）
            if ('PRINTF_COND' in stripped_line or 
                '$fwrite' in stripped_line or
                'io_timer' in stripped_line):  # io_timer 通常是 $fwrite 的参数
                continue  # 跳过打印相关的行
            
            matched_lines.append(stripped_line)  # 存储去除空格的版本以保持整洁
        
        # 检查模块结束
        if stripped_line.startswith("endmodule"):
            if in_target_module:
                break  # 目标模块结束，退出循环
            in_target_module = False
    
    return matched_lines
