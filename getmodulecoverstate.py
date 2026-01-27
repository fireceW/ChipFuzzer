# from config import Coverage_filename_origin





def count_percentage_prefix_by_module(verilog_code, prefix="%000000"):
    lines = verilog_code.splitlines()
    module_count = {}
    current_module = None
    total_modules = 0  # 统计模块总数

    for line in lines:
        # 查找模块开始
        if "module " in line:
            # 解析模块名称
            current_module = line.split()[1].split("(")[0]  # 获取模块名
            module_count[current_module] = {
                "count": 0,  # %000000 出现次数
                "line_length": 0  # 行长度
            }
            total_modules += 1  # 模块总数加一
        
        # 统计当前模块中的前缀
        if current_module:
            module_count[current_module]["count"] += line.count(prefix)
            module_count[current_module]["line_length"] += len(line)  # 统计行长度

        # 查找模块结束
        if "endmodule" in line:
            current_module = None  # 重置当前模块

    # 按照前缀出现次数排序
    sorted_modules = sorted(module_count.items(), key=lambda item: item[1]["count"], reverse=True)
    
    return sorted_modules, total_modules

# 调用函数并打印结果
def getTheMostUncoveredModule(num, Coverage_filename_origin):

    filename = Coverage_filename_origin
    with open(filename,"r") as file:
        verilog_code = file.read()
    
    result, total_modules = count_percentage_prefix_by_module(verilog_code)
    print(len(result))
    
    # for module, info in result: 
    #     print(f"模块 '{module}' 中前缀 '{'%000000'}' 的出现次数: {info['count']}")
    # print(f"总模块个数: {total_modules}")
    print(result[num][0])

    return result[num][0]

# getTheMostUncoveredModule()

def getTopUncoveredModules(num, Coverage_filename_origin_dir):
    """
    获取未覆盖代码最多的 num 个模块列表
    
    参数:
        num: 要返回的模块数量
        Coverage_filename_origin_dir: annotated 目录路径
        
    返回:
        模块名称列表
    """
    import os
    import glob
    
    # 获取目录下所有 .sv 文件
    sv_files = glob.glob(os.path.join(Coverage_filename_origin_dir, "*.sv"))
    
    module_uncovered_counts = []
    
    for sv_file in sv_files:
        module_name = os.path.basename(sv_file).replace(".sv", "")
        
        try:
            with open(sv_file, "r", encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # 统计未覆盖代码行数
            uncovered_count = content.count("%000000")
            
            # 过滤掉 PRINTF_COND 相关的行（这些通常不需要测试）
            if uncovered_count > 0:
                module_uncovered_counts.append((module_name, uncovered_count))
        except Exception as e:
            print(f"⚠️ 读取文件失败 {sv_file}: {e}")
    
    # 按未覆盖代码行数排序（从多到少）
    module_uncovered_counts.sort(key=lambda x: x[1], reverse=True)
    
    # 返回前 num 个模块名
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
