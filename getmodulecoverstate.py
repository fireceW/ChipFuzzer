# from config import Coverage_filename_origin





def count_percentage_prefix_by_module(verilog_code, prefix="%000000"):
    lines = verilog_code.splitlines()
    module_count = {}
    current_module = None
    total_modules = 0  # Total number of statistical modules

    for line in lines:
        # Find module start
        if "module " in line:
            # Parse module name
            current_module = line.split()[1].split("(")[0]  # Get module name
            module_count[current_module] = {
                "count": 0,  # %000000 number of occurrences
                "line_length": 0  # line length
            }
            total_modules += 1  # Add one to the total number of modules
        
        # Count prefixes in the current module
        if current_module:
            module_count[current_module]["count"] += line.count(prefix)
            module_count[current_module]["line_length"] += len(line)  # Statistics line length

        # End of search module
        if "endmodule" in line:
            current_module = None  # Reset current module

    # Sort by number of prefix occurrences
    sorted_modules = sorted(module_count.items(), key=lambda item: item[1]["count"], reverse=True)
    
    return sorted_modules, total_modules

# Call a function and print the result
def getTheMostUncoveredModule(num, Coverage_filename_origin):

    filename = Coverage_filename_origin
    with open(filename,"r") as file:
        verilog_code = file.read()
    
    result, total_modules = count_percentage_prefix_by_module(verilog_code)
    print(len(result))
    
    # for module, info in result: 
    # print(f"The number of occurrences of the prefix '{'%000000'}' in module '{module}': {info['count']}")
    # print(f"Total number of modules: {total_modules}")
    print(result[num][0])

    return result[num][0]

# getTheMostUncoveredModule()

def getTopUncoveredModules(num, Coverage_filename_origin_dir):
    """
    Get a list of num modules with the most uncovered code
    
    parameter:
        num: number of modules to return
        Coverage_filename_origin_dir: annotated directory path
        
    return:
        module name list
    """
    import os
    import glob
    
    # Get all .sv files in the directory
    sv_files = glob.glob(os.path.join(Coverage_filename_origin_dir, "*.sv"))
    
    module_uncovered_counts = []
    
    for sv_file in sv_files:
        module_name = os.path.basename(sv_file).replace(".sv", "")
        
        try:
            with open(sv_file, "r", encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Count the number of lines of code not covered
            uncovered_count = content.count("%000000")
            
            # Filter out PRINTF_COND related lines (these usually don't need to be tested)
            if uncovered_count > 0:
                module_uncovered_counts.append((module_name, uncovered_count))
        except Exception as e:
            print(f"⚠️ 读取文件失败 {sv_file}: {e}")
    
    # Sort by number of uncovered lines of code (from most to least)
    module_uncovered_counts.sort(key=lambda x: x[1], reverse=True)
    
    # Returns the first num module names
    result = [m[0] for m in module_uncovered_counts[:num]]
    
    print(f"📊 未覆盖代码最多的 {num} 个模块:")
    for i, (name, count) in enumerate(module_uncovered_counts[:num]):
        print(f"   {i+1}. {name}: {count} 行未覆盖")
    
    return result


def getTheMostUncoveredModule_debug(Coverage_filename_origin):

    filename = Coverage_filename_origin
    with open(filename,"r") as file:
        verilog_code = file.read()
    
    result, total_modules = count_percentage_prefix_by_module(verilog_code)

    return total_modules
