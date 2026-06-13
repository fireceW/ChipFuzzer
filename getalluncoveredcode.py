from getmodulecoverstate import getTheMostUncoveredModule, getTheMostUncoveredModule_debug
from getuncoveredcodeline import extract_lines_with_prefix_origin
import json

def filter_print_cond_blocks(code_lines):
    """Filter out the if (`PRINTF_COND) begin ... $fwrite code block"""
    filtered = []
    skip = False
    
    for line in code_lines:
        if 'if (`PRINTF_COND) begin' in line:
            skip = True  # Start skipping
        elif skip and '$fwrite' in line:
            skip = False  # Stop skipping after encountering $fwrite
            continue      # Skip current $fwrite line
        elif not skip:
            filtered.append(line)
    
    return filtered








def get_uncovered_code(Coverage_filename_origin, Coverage_filename_later):
    all_code = []  # Store all uncovered lines of code
    flag = True
    module_num = getTheMostUncoveredModule_debug(Coverage_filename_origin)
    if module_num < 233:
        flag = False
        return all_code , flag 
    else:
        flag = True
        for num in range(172):
            testing_module = getTheMostUncoveredModule(num ,Coverage_filename_origin)
            # print(f"the testing module is :::{testing_module}")
            # print(f"start to analyze the {testing_module} module")
            
            # Get uncovered lines of code
            uncovered_code_all, file_infos_all, line_numbers = extract_lines_with_prefix_origin(testing_module,Coverage_filename_origin)
            uncovered_code_all = filter_print_cond_blocks(uncovered_code_all)
            # print(uncovered_code_all)
            # exit()
            
            # Use extend() instead of append() to flatten lists
            all_code.extend(uncovered_code_all)
    
    # Save to JSON file
    # with open('uncovered_code.json', 'w', encoding='utf-8') as f:
    #     json.dump(all_code, f, ensure_ascii=False, indent=2)
    
    # print(f"Saved {len(all_code)} uncovered code lines to uncovered_code.json")
    
        return all_code , flag

