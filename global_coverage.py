"""
全局覆盖率管理模块
负责统计和更新整个项目的代码覆盖率，而不仅仅是单个模块
"""

import os
import glob
import re
import subprocess
import json
from typing import Tuple, List, Optional, Dict

# 需要单独统计的模块组
TRACKED_MODULE_GROUPS = {
    "L2": [
        "L2Cache",
        "L2DataStorage",
        "L2DataStorage_1", 
        "L2Directory",
        "L2Directory_1",
        "L2TLB",
        "L2TLBWrapper",
        "L2TlbPrefetch",
        "L2Top",
    ],
}


class GlobalCoverageManager:
    """
    管理全局覆盖率统计
    - 遍历 annotated 目录下的所有 .sv 文件
    - 统计所有模块的未覆盖代码行数
    - 合并覆盖率数据并更新报告
    """

    def __init__(self, project_root: str, annotated_dir: str, sum_dat_file: str = None):
        """
        参数:
            project_root: 项目根目录 (如 /root/XiangShan)
            annotated_dir: annotated 目录路径 (如 /root/XiangShan/logs_testcase/annotated)
            sum_dat_file: 累积覆盖率文件路径 (默认为 project_root/sum_gj.dat)
        """
        self.project_root = project_root
        self.annotated_dir = annotated_dir
        self.sum_dat_file = sum_dat_file or os.path.join(project_root, "sum_gj.dat")
        
        # 初始化时统计基线
        self.baseline_uncovered_count = 0
        self.baseline_uncovered_lines = []
        
        # 标记是否是 Fresh 模式（通过检查 annotated 目录是否为空且 sum_gj.dat 不存在）
        # 如果 annotated 目录为空且 sum_gj.dat 不存在，说明是 Fresh 模式
        annotated_empty = not os.path.exists(self.annotated_dir) or \
                         (os.path.exists(self.annotated_dir) and 
                          len(glob.glob(os.path.join(self.annotated_dir, "*.sv"))) == 0)
        sum_dat_missing = not os.path.exists(self.sum_dat_file) or os.path.getsize(self.sum_dat_file) == 0
        self.is_fresh_mode = annotated_empty and sum_dat_missing
        
        # 调试日志
        print(f"🔍 [GlobalCoverageManager.__init__] 初始化检查:")
        print(f"   annotated_dir: {self.annotated_dir}")
        print(f"   annotated_empty: {annotated_empty}")
        print(f"   sum_dat_file: {self.sum_dat_file}")
        print(f"   sum_dat_missing: {sum_dat_missing}")
        print(f"   is_fresh_mode: {self.is_fresh_mode}")
        
        # 如果 annotated 目录为空但 sum_gj.dat 存在，先恢复 annotated 报告
        # 这通常发生在 continue 模式下，annotated 目录被意外清空
        # 但在 Fresh 模式下，不应该恢复（因为 sum_gj.dat 应该已被删除）
        if not self.is_fresh_mode:
            self._restore_annotated_if_needed()
        
        self._update_baseline()
    
    def _restore_annotated_if_needed(self) -> bool:
        """
        如果需要，从 sum_gj.dat 恢复 annotated 报告
        
        返回:
            是否成功恢复
        """
        if os.path.exists(self.sum_dat_file) and os.path.getsize(self.sum_dat_file) > 0:
            # 检查 annotated 目录是否存在且有文件
            has_files = False
            if os.path.exists(self.annotated_dir):
                sv_files = glob.glob(os.path.join(self.annotated_dir, "*.sv"))
                has_files = len(sv_files) > 0
            
            if not has_files:
                print(f"⚠️ annotated 目录为空但 sum_gj.dat 存在，尝试恢复 annotated 报告...")
                if self.update_annotated_report():
                    print(f"✅ 已从 sum_gj.dat 恢复 annotated 报告")
                    return True
                else:
                    print(f"⚠️ 恢复 annotated 报告失败")
                    return False
        return False

    def _update_baseline(self):
        """更新基线统计"""
        # 如果是 Fresh 模式，基线应该保持为 0，不统计
        if getattr(self, 'is_fresh_mode', False):
            print(f"📊 Fresh 模式：基线保持为 0（等待首次测试后设置新基线）")
            self.baseline_uncovered_count = 0
            self.baseline_uncovered_lines = []
            return
        
        # 如果 annotated 目录存在且有文件，才统计基线
        # 如果目录为空（fresh 模式刚重置），基线保持为 0，等第一次测试后再设置
        if os.path.exists(self.annotated_dir):
            sv_files = glob.glob(os.path.join(self.annotated_dir, "*.sv"))
            if sv_files:  # 目录中有文件才统计
                self.baseline_uncovered_lines = self.get_all_uncovered_lines()
                self.baseline_uncovered_count = len(self.baseline_uncovered_lines)
                print(f"📊 全局基线: {self.baseline_uncovered_count} 行未覆盖代码")
            else:
                print(f"📊 全局基线: 0 行未覆盖代码（annotated 目录为空，等待首次测试）")
                self.baseline_uncovered_count = 0
                self.baseline_uncovered_lines = []
        else:
            print(f"📊 全局基线: 0 行未覆盖代码（annotated 目录不存在）")
            self.baseline_uncovered_count = 0
            self.baseline_uncovered_lines = []

    def reset_coverage(self, backup: bool = True, reset_annotated: bool = True) -> bool:
        """
        重置覆盖率文件，开始新的测试周期
        
        参数:
            backup: 是否备份旧的 sum_gj.dat 文件
            reset_annotated: 是否重置 annotated 目录
            
        返回:
            是否成功重置
        """
        import shutil
        import time
        
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            
            # 1. 备份并删除 sum_gj.dat
            if os.path.exists(self.sum_dat_file):
                if backup:
                    backup_file = f"{self.sum_dat_file}.backup_{timestamp}"
                    shutil.copy2(self.sum_dat_file, backup_file)
                    print(f"📦 已备份旧覆盖率文件: {backup_file}")
                
                os.remove(self.sum_dat_file)
                print(f"🗑️ 已删除旧覆盖率文件: {self.sum_dat_file}")
            
            # 2. 重置 annotated 目录（清空全局累积目录的内容）
            if reset_annotated and os.path.exists(self.annotated_dir):
                if backup:
                    backup_dir = f"{self.annotated_dir}.backup_{timestamp}"
                    if os.path.exists(backup_dir):
                        shutil.rmtree(backup_dir)
                    shutil.copytree(self.annotated_dir, backup_dir)
                    print(f"📦 已备份旧 annotated 目录: {backup_dir}")
                
                # 清空目录内容（但保留目录本身）
                for item in os.listdir(self.annotated_dir):
                    item_path = os.path.join(self.annotated_dir, item)
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                print(f"🗑️ 已清空 annotated 目录: {self.annotated_dir}")
            
            # 3. 删除 coverage.info（让它在新测试中重新生成）
            coverage_info_file = os.path.join(self.project_root, "coverage.info")
            if os.path.exists(coverage_info_file):
                if backup:
                    backup_coverage = f"{coverage_info_file}.backup_{timestamp}"
                    shutil.copy2(coverage_info_file, backup_coverage)
                    print(f"📦 已备份旧 coverage.info: {backup_coverage}")
                os.remove(coverage_info_file)
                print(f"🗑️ 已删除旧 coverage.info")
            
            # 在 Fresh 模式下，强制重置基线为 0
            # 不要调用 _update_baseline()，因为 annotated 目录可能还有残留文件
            self.baseline_uncovered_count = 0
            self.baseline_uncovered_lines = []
            # 标记为 Fresh 模式
            self.is_fresh_mode = True
            print(f"📊 Fresh 模式：基线已重置为 0（等待首次测试后设置新基线）")
            print(f"✅ Fresh 模式：所有覆盖率数据已重置，开始全新的测试周期")
            return True
            
        except Exception as e:
            print(f"❌ 重置覆盖率文件失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_coverage_info(self) -> dict:
        """
        获取当前覆盖率信息
        
        返回:
            包含覆盖率统计的字典
        """
        info = {
            "sum_dat_exists": os.path.exists(self.sum_dat_file),
            "sum_dat_file": self.sum_dat_file,
            "annotated_dir": self.annotated_dir,
            "baseline_uncovered_count": self.baseline_uncovered_count,
        }
        
        if info["sum_dat_exists"]:
            stat = os.stat(self.sum_dat_file)
            info["sum_dat_size"] = stat.st_size
            info["sum_dat_mtime"] = stat.st_mtime
        
        return info

    def get_total_coverage_from_genhtml(self) -> dict:
        """
        通过 genhtml 获取总覆盖率百分比
        
        返回:
            包含覆盖率百分比的字典
        """
        import re
        coverage_info_file = os.path.join(self.project_root, "coverage.info")
        
        # 如果 coverage.info 不存在，尝试从 sum_gj.dat 生成
        if not os.path.exists(coverage_info_file):
            # 检查是否是 Fresh 模式（sum_gj.dat 也不存在）
            if not os.path.exists(self.sum_dat_file) or os.path.getsize(self.sum_dat_file) == 0:
                return {"coverage_percentage": 0.0, "covered": 0, "total": 0, "status": "no_data", "message": "Fresh 模式：等待首次测试数据"}
            
            # 如果不是 Fresh 模式，尝试从 sum_gj.dat 生成 coverage.info
            print(f"⚠️ coverage.info 不存在，尝试从 sum_gj.dat 生成...")
            if self.update_coverage_info():
                print(f"✅ 已从 sum_gj.dat 生成 coverage.info")
            else:
                return {"coverage_percentage": 0.0, "covered": 0, "total": 0, "status": "error", "message": "无法从 sum_gj.dat 生成 coverage.info"}
        
        try:
            result = subprocess.run(
                ["genhtml", "coverage.info", "--output-directory", "coverage_gj"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=300,
            )
            
            output = result.stdout + result.stderr
            
            # 解析 "Overall coverage rate: lines......: 72.2% (463483 of 642121 lines)"
            match = re.search(r'lines\.+:\s*([\d.]+)%\s*\((\d+)\s+of\s+(\d+)\s+lines\)', output)
            
            if match:
                percentage = float(match.group(1))
                covered = int(match.group(2))
                total = int(match.group(3))
                return {
                    "coverage_percentage": percentage,  # 统一使用 coverage_percentage
                    "percentage": percentage,  # 保持向后兼容
                    "covered": covered,
                    "total": total,
                    "status": "ok"
                }
            else:
                return {"coverage_percentage": 0.0, "percentage": 0.0, "covered": 0, "total": 0, "status": "parse_error", "message": "无法解析 genhtml 输出"}
                
        except Exception as e:
            return {"coverage_percentage": 0.0, "percentage": 0.0, "covered": 0, "total": 0, "status": f"error: {e}"}

    def print_total_coverage(self, title: str = "总覆盖率") -> dict:
        """
        打印总覆盖率信息
        
        参数:
            title: 显示的标题
            
        返回:
            覆盖率信息字典
        """
        cov = self.get_total_coverage_from_genhtml()
        
        print(f"\n{'='*60}")
        print(f"📊 {title}")
        print(f"{'='*60}")
        
        if cov["status"] == "ok":
            print(f"   覆盖率: {cov['percentage']:.2f}%")
            print(f"   已覆盖: {cov['covered']:,} 行")
            print(f"   总行数: {cov['total']:,} 行")
            print(f"   未覆盖: {cov['total'] - cov['covered']:,} 行")
        elif cov["status"] == "no_data":
            print(f"   状态: 暂无覆盖率数据（coverage.info 不存在）")
        else:
            print(f"   状态: {cov['status']}")
        
        print(f"{'='*60}\n")
        
        return cov

    def get_module_coverage_stats(self, module_name: str) -> Dict:
        """
        获取单个模块的覆盖率统计
        
        参数:
            module_name: 模块名（不含 .sv 后缀）
            
        返回:
            包含覆盖率统计的字典
        """
        sv_file = os.path.join(self.annotated_dir, f"{module_name}.sv")
        
        if not os.path.exists(sv_file):
            return {"exists": False, "module": module_name}
        
        total_lines = 0
        covered_lines = 0
        uncovered_lines = 0
        
        try:
            with open(sv_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    stripped = line.strip()
                    # 跳过空行和纯注释行
                    if not stripped or stripped.startswith('//'):
                        continue
                    
                    # 检查覆盖率标记（使用正则表达式匹配，更准确）
                    if '%' in stripped:
                        coverage_markers = re.findall(r'%(\d{6})', stripped)
                        if coverage_markers:
                            total_lines += 1
                            # 检查是否有非零的覆盖率标记（表示已覆盖）
                            has_covered = any(marker != '000000' for marker in coverage_markers)
                            if has_covered:
                                covered_lines += 1
                            else:
                                uncovered_lines += 1
            
            coverage_rate = (covered_lines / total_lines * 100) if total_lines > 0 else 0
            
            return {
                "exists": True,
                "module": module_name,
                "total_lines": total_lines,
                "covered_lines": covered_lines,
                "uncovered_lines": uncovered_lines,
                "coverage_rate": coverage_rate,
            }
        except Exception as e:
            return {"exists": False, "module": module_name, "error": str(e)}

    def get_module_group_stats(self, group_name: str = None) -> Dict:
        """
        获取模块组的覆盖率统计
        
        参数:
            group_name: 模块组名（如 "L2"），为 None 则统计所有组
            
        返回:
            包含各模块覆盖率的字典
        """
        results = {}
        
        groups_to_check = TRACKED_MODULE_GROUPS
        if group_name and group_name in TRACKED_MODULE_GROUPS:
            groups_to_check = {group_name: TRACKED_MODULE_GROUPS[group_name]}
        
        for gname, modules in groups_to_check.items():
            group_stats = {
                "modules": {},
                "total_lines": 0,
                "covered_lines": 0,
                "uncovered_lines": 0,
            }
            
            for module in modules:
                stats = self.get_module_coverage_stats(module)
                group_stats["modules"][module] = stats
                
                if stats.get("exists"):
                    group_stats["total_lines"] += stats["total_lines"]
                    group_stats["covered_lines"] += stats["covered_lines"]
                    group_stats["uncovered_lines"] += stats["uncovered_lines"]
            
            if group_stats["total_lines"] > 0:
                group_stats["coverage_rate"] = (
                    group_stats["covered_lines"] / group_stats["total_lines"] * 100
                )
            else:
                group_stats["coverage_rate"] = 0
            
            results[gname] = group_stats
        
        return results

    def print_module_group_stats(self, group_name: str = None):
        """
        打印模块组的覆盖率统计
        """
        stats = self.get_module_group_stats(group_name)
        
        for gname, gstats in stats.items():
            print(f"\n{'='*60}")
            print(f"📊 {gname} 模块组覆盖率统计")
            print(f"{'='*60}")
            print(f"{'模块名':<25} {'覆盖率':>10} {'已覆盖':>12} {'未覆盖':>10}")
            print(f"{'-'*60}")
            
            for module, mstats in gstats["modules"].items():
                if mstats.get("exists"):
                    rate = mstats["coverage_rate"]
                    # 根据覆盖率选择颜色标记
                    if rate >= 90:
                        status = "🟢"
                    elif rate >= 70:
                        status = "🟡"
                    else:
                        status = "🔴"
                    
                    print(f"{status} {module:<23} {rate:>8.1f}% "
                          f"{mstats['covered_lines']:>8}/{mstats['total_lines']:<6} "
                          f"{mstats['uncovered_lines']:>6}")
                else:
                    print(f"⚪ {module:<23} {'N/A':>10} {'文件不存在':>20}")
            
            print(f"{'-'*60}")
            print(f"{'汇总':<25} {gstats['coverage_rate']:>8.1f}% "
                  f"{gstats['covered_lines']:>8}/{gstats['total_lines']:<6} "
                  f"{gstats['uncovered_lines']:>6}")
            print(f"{'='*60}")

    def get_all_uncovered_lines(self, prefix: str = "%000000") -> List[str]:
        """
        统计 annotated 目录下所有 .sv 文件的未覆盖代码行
        
        返回:
            包含所有未覆盖代码行的列表
        """
        all_uncovered = []
        
        # 检查目录是否存在
        if not os.path.exists(self.annotated_dir):
            print(f"⚠️ annotated 目录不存在: {self.annotated_dir}")
            return all_uncovered
        
        # 遍历所有 .sv 文件
        sv_files = glob.glob(os.path.join(self.annotated_dir, "*.sv"))
        
        for sv_file in sv_files:
            try:
                with open(sv_file, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        stripped = line.strip()
                        # 跳过空行和纯注释行
                        if not stripped or stripped.startswith('//'):
                            continue
                        
                        # 使用正则表达式匹配覆盖率标记，确保准确性
                        if '%' in stripped:
                            coverage_markers = re.findall(r'%(\d{6})', stripped)
                            # 如果所有标记都是 000000，说明未覆盖
                            if coverage_markers and all(marker == '000000' for marker in coverage_markers):
                                # 过滤掉所有打印相关的代码行（包括 $fwrite 及其续行）
                                if ('PRINTF_COND' not in stripped and 
                                    '$fwrite' not in stripped and
                                    'io_timer' not in stripped):  # io_timer 通常是 $fwrite 的参数
                                    all_uncovered.append(stripped)
            except Exception as e:
                print(f"⚠️ 读取文件失败 {sv_file}: {e}")
        
        return all_uncovered

    def count_uncovered_by_module(self, prefix: str = "%000000") -> dict:
        """
        按模块统计未覆盖代码行数
        
        返回:
            {模块名: 未覆盖行数} 的字典
        """
        module_stats = {}
        sv_files = glob.glob(os.path.join(self.annotated_dir, "*.sv"))
        
        for sv_file in sv_files:
            module_name = os.path.basename(sv_file).replace('.sv', '')
            count = 0
            try:
                with open(sv_file, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        stripped = line.strip()
                        # 跳过空行和纯注释行
                        if not stripped or stripped.startswith('//'):
                            continue
                        
                        # 使用正则表达式匹配覆盖率标记
                        if '%' in stripped:
                            coverage_markers = re.findall(r'%(\d{6})', stripped)
                            # 如果所有标记都是 000000，说明未覆盖
                            if coverage_markers and all(marker == '000000' for marker in coverage_markers):
                                # 过滤掉所有打印相关的代码行
                                if ('PRINTF_COND' not in stripped and 
                                    '$fwrite' not in stripped and
                                    'io_timer' not in stripped):  # io_timer 通常是 $fwrite 的参数
                                    count += 1
                module_stats[module_name] = count
            except Exception as e:
                print(f"⚠️ 读取文件失败 {sv_file}: {e}")
        
        return module_stats

    def merge_coverage_dat(self, new_dat_file: str) -> bool:
        """
        将新的 .dat 文件合并到累积覆盖率文件
        
        参数:
            new_dat_file: 新生成的 coverage.dat 文件路径
            
        返回:
            是否成功
        """
        # 检查新文件是否存在
        if not os.path.exists(new_dat_file):
            print(f"❌ 覆盖率文件不存在: {new_dat_file}")
            return False
        
        # 检查新文件大小
        new_file_size = os.path.getsize(new_dat_file)
        if new_file_size == 0:
            print(f"⚠️ 覆盖率文件为空: {new_dat_file}")
            return False
        
        try:
            if os.path.exists(self.sum_dat_file) and os.path.getsize(self.sum_dat_file) > 0:
                # 检查旧文件大小
                old_file_size = os.path.getsize(self.sum_dat_file)
                print(f"📊 合并覆盖率数据: 旧文件 {old_file_size / 1024:.1f} KB + 新文件 {new_file_size / 1024:.1f} KB")
                # 合并已有的和新的
                cmd = f"verilator_coverage -write {self.sum_dat_file} {self.sum_dat_file} {new_dat_file}"
            else:
                # 第一次（Fresh 模式或首次运行），直接复制
                print(f"📊 首次创建累积覆盖率文件: {new_file_size / 1024:.1f} KB")
                cmd = f"verilator_coverage -write {self.sum_dat_file} {new_dat_file}"
            
            print(f"\n{'='*60}")
            print(f"📊 [覆盖率合并] 执行命令")
            print(f"{'='*60}")
            print(f"📂 工作目录: {self.project_root}")
            print(f"💻 命令: {cmd}")
            print(f"-" * 60)
            
            import time as _time
            start_time = _time.time()
            result = subprocess.run(
                cmd, shell=True, cwd=self.project_root,
                capture_output=True, text=True, timeout=300
            )
            elapsed = _time.time() - start_time
            
            if result.returncode != 0:
                print(f"❌ 合并覆盖率数据失败")
                print(f"   返回值: {result.returncode}")
                print(f"   错误: {result.stderr}")
                print(f"{'='*60}\n")
                return False
            
            # 验证合并后的文件
            if not os.path.exists(self.sum_dat_file):
                print(f"❌ 合并后文件不存在: {self.sum_dat_file}")
                return False
            
            merged_file_size = os.path.getsize(self.sum_dat_file)
            print(f"✅ 合并成功")
            print(f"   耗时: {elapsed:.2f} 秒")
            print(f"   合并后文件大小: {merged_file_size / 1024:.1f} KB")
            if result.stdout:
                print(f"   输出: {result.stdout.strip()}")
            print(f"{'='*60}\n")
            return True
            
        except Exception as e:
            print(f"❌ 合并覆盖率数据异常: {e}")
            return False

    def update_annotated_report(self) -> bool:
        """
        使用累积的覆盖率数据更新 annotated 报告
        
        返回:
            是否成功
        """
        if not os.path.exists(self.sum_dat_file):
            print(f"⚠️ 累积覆盖率文件不存在: {self.sum_dat_file}")
            return False
        
        try:
            cmd = f"verilator_coverage -annotate {self.annotated_dir} {self.sum_dat_file}"
            
            print(f"\n{'='*60}")
            print(f"📊 [更新 Annotated 报告] 执行命令")
            print(f"{'='*60}")
            print(f"📂 工作目录: {self.project_root}")
            print(f"💻 命令: {cmd}")
            print(f"-" * 60)
            
            import time as _time
            start_time = _time.time()
            result = subprocess.run(
                cmd, shell=True, cwd=self.project_root,
                capture_output=True, text=True, timeout=300
            )
            elapsed = _time.time() - start_time
            
            if result.returncode != 0:
                print(f"❌ 更新覆盖率报告失败")
                print(f"   返回值: {result.returncode}")
                print(f"   错误: {result.stderr}")
                print(f"{'='*60}\n")
                return False
            
            print(f"✅ 更新成功")
            print(f"   耗时: {elapsed:.2f} 秒")
            print(f"   目标目录: {self.annotated_dir}")
            print(f"{'='*60}\n")
            return True
            
        except Exception as e:
            print(f"❌ 更新覆盖率报告异常: {e}")
            return False

    def update_coverage_info(self) -> bool:
        """
        更新 coverage.info 文件（用于 genhtml 等工具）
        """
        if not os.path.exists(self.sum_dat_file):
            return False
        
        try:
            cmd = f"verilator_coverage -write-info coverage.info {self.sum_dat_file}"
            
            print(f"\n{'='*60}")
            print(f"📊 [更新 coverage.info] 执行命令")
            print(f"{'='*60}")
            print(f"📂 工作目录: {self.project_root}")
            print(f"💻 命令: {cmd}")
            print(f"-" * 60)
            
            import time as _time
            start_time = _time.time()
            result = subprocess.run(
                cmd, shell=True, cwd=self.project_root,
                capture_output=True, text=True, timeout=300
            )
            elapsed = _time.time() - start_time
            
            if result.returncode == 0:
                print(f"✅ 更新成功")
                print(f"   耗时: {elapsed:.2f} 秒")
                print(f"   输出文件: {self.project_root}/coverage.info")
            else:
                print(f"❌ 更新失败")
                print(f"   返回值: {result.returncode}")
                if result.stderr:
                    print(f"   错误: {result.stderr}")
            print(f"{'='*60}\n")
            
            return result.returncode == 0
        except Exception as e:
            print(f"❌ 更新 coverage.info 失败: {e}")
            return False

    def check_global_improvement(self, new_dat_file: str) -> Tuple[bool, int, List[str]]:
        """
        检查运行测试后全局覆盖率是否有提升
        
        参数:
            new_dat_file: 新生成的 coverage.dat 文件路径
            
        返回:
            (是否有提升, 减少的行数, 新覆盖的代码行列表)
        """
        print(f"🔄 正在更新全局覆盖率数据...")
        print(f"   当前基线: {self.baseline_uncovered_count} 行未覆盖")
        print(f"   Fresh 模式: {getattr(self, 'is_fresh_mode', False)}")
        
        # 1. 合并新的覆盖率数据
        if not self.merge_coverage_dat(new_dat_file):
            print(f"❌ 合并覆盖率数据失败")
            return False, 0, []
        
        # 2. 更新 annotated 报告
        if not self.update_annotated_report():
            print(f"❌ 更新 annotated 报告失败")
            return False, 0, []
        
        print(f"✅ 全局 annotated 目录已更新: {self.annotated_dir}")
        
        # 3. 更新 coverage.info
        if self.update_coverage_info():
            print(f"✅ coverage.info 已更新")
        
        # 4. 重新统计未覆盖代码行
        new_uncovered_lines = self.get_all_uncovered_lines()
        new_uncovered_count = len(new_uncovered_lines)
        print(f"   新统计: {new_uncovered_count} 行未覆盖")
        
        # 特殊处理：如果基线是 0（fresh 模式或首次运行），用当前结果设置基线
        # 但需要确保这是真正的首次运行，而不是因为 annotated 目录被清空
        if self.baseline_uncovered_count == 0 and new_uncovered_count > 0:
            # 如果是 Fresh 模式，直接设置基线，不尝试恢复
            if getattr(self, 'is_fresh_mode', False):
                # Fresh 模式：直接设置基线，不尝试从 sum_gj.dat 恢复
                print(f"📊 Fresh 模式：首次统计全局覆盖率")
                print(f"   设置基线: {new_uncovered_count} 行未覆盖代码")
                print(f"   注意：这是首次测试后的基线，后续测试将以此为基础计算提升")
                self.baseline_uncovered_count = new_uncovered_count
                self.baseline_uncovered_lines = new_uncovered_lines
                # 标记 Fresh 模式已完成首次基线设置
                self.is_fresh_mode = False
                # 首次设置基线，不算作"提升"，返回 False
                return False, 0, []
            
            # 检查 sum_gj.dat 是否存在且不为空
            sum_dat_exists = os.path.exists(self.sum_dat_file) and os.path.getsize(self.sum_dat_file) > 0
            
            if not sum_dat_exists:
                # 真正的首次运行（fresh 模式），设置基线
                print(f"📊 首次统计全局覆盖率，设置基线: {new_uncovered_count} 行未覆盖")
                self.baseline_uncovered_count = new_uncovered_count
                self.baseline_uncovered_lines = new_uncovered_lines
                # 首次设置基线，不算作"提升"，返回 False
                return False, 0, []
            else:
                # sum_gj.dat 存在但基线是 0，说明可能是 continue 模式下 annotated 目录被意外清空
                # 这种情况下，应该从 sum_gj.dat 重新生成 annotated 报告，然后统计基线
                # 注意：这不应该发生，因为在 __init__ 中已经尝试恢复了
                # 但如果发生了，再次尝试恢复
                print(f"⚠️ 基线为 0 但 sum_gj.dat 存在，尝试从 sum_gj.dat 恢复基线...")
                if self._restore_annotated_if_needed():
                    # 重新统计基线
                    self.baseline_uncovered_lines = self.get_all_uncovered_lines()
                    self.baseline_uncovered_count = len(self.baseline_uncovered_lines)
                    print(f"📊 已恢复基线: {self.baseline_uncovered_count} 行未覆盖代码")
                else:
                    # 恢复失败，使用当前结果作为基线（但记录警告）
                    print(f"⚠️ 恢复失败，使用当前结果设置基线: {new_uncovered_count} 行未覆盖")
                    print(f"   警告：这可能导致基线不准确，建议检查 annotated 目录状态")
                    self.baseline_uncovered_count = new_uncovered_count
                    self.baseline_uncovered_lines = new_uncovered_lines
                return False, 0, []
        
        # 5. 计算差异
        reduced_count = self.baseline_uncovered_count - new_uncovered_count
        
        # 找出新覆盖的行（在旧基线中但不在新统计中）
        new_uncovered_set = set(new_uncovered_lines)
        newly_covered = [
            line for line in self.baseline_uncovered_lines 
            if line not in new_uncovered_set
        ]
        
        # 6. 判断是否有提升（未覆盖行数减少 = 覆盖率提升）
        improved = new_uncovered_count < self.baseline_uncovered_count
        
        # 安全检查：如果新未覆盖行数异常大（比基线大很多），可能是统计错误
        # 这种情况下不更新基线，避免覆盖率看起来下降
        if self.baseline_uncovered_count > 0:
            if new_uncovered_count > self.baseline_uncovered_count * 1.1:
                print(f"⚠️ 警告：新未覆盖行数 ({new_uncovered_count}) 比基线 ({self.baseline_uncovered_count}) 大 10% 以上")
                print(f"   可能是统计错误或 annotated 目录数据不一致，保持基线不变")
                print(f"   建议检查 annotated 目录和 sum_gj.dat 是否同步")
                return False, 0, []
            
            # 额外检查：如果新未覆盖行数比基线大，但不超过 10%，记录警告但不阻止
            if new_uncovered_count > self.baseline_uncovered_count:
                print(f"⚠️ 注意：新未覆盖行数 ({new_uncovered_count}) 比基线 ({self.baseline_uncovered_count}) 大")
                print(f"   这不应该发生，可能是数据不一致，但差异较小，继续处理")
        
        if improved:
            print(f"🎉 全局覆盖率提升！")
            print(f"   未覆盖代码: {self.baseline_uncovered_count} → {new_uncovered_count}")
            print(f"   减少了 {reduced_count} 行未覆盖代码")
            
            # 显示部分新覆盖的代码行
            if newly_covered:
                print(f"   新覆盖的代码行 (前 10 行):")
                for i, line in enumerate(newly_covered[:10]):
                    # 截取显示，避免太长
                    display_line = line[:80] + "..." if len(line) > 80 else line
                    print(f"   {i+1}. {display_line}")
                if len(newly_covered) > 10:
                    print(f"   还有 {len(newly_covered) - 10} 行...")
            
            # 更新基线（只有在确实有提升时才更新）
            self.baseline_uncovered_count = new_uncovered_count
            self.baseline_uncovered_lines = new_uncovered_lines
            
            # 验证数据一致性：检查 sum_gj.dat 和 annotated 目录是否同步
            self._verify_data_consistency()
        else:
            if new_uncovered_count == self.baseline_uncovered_count:
                print(f"ℹ️ 全局覆盖率无变化: {new_uncovered_count} 行未覆盖 (基线: {self.baseline_uncovered_count})")
            else:
                # 这种情况不应该发生（已经在前面检查过了）
                print(f"⚠️ 全局覆盖率异常: 新未覆盖行数 ({new_uncovered_count}) != 基线 ({self.baseline_uncovered_count})")
                print(f"   保持基线不变")
        
        return improved, reduced_count, newly_covered

    def _verify_data_consistency(self):
        """验证数据一致性：检查 sum_gj.dat 和 annotated 目录是否同步"""
        try:
            # 检查 sum_gj.dat 是否存在
            if not os.path.exists(self.sum_dat_file):
                print(f"⚠️ 数据一致性检查：sum_gj.dat 不存在")
                return False
            
            # 检查 annotated 目录是否有文件
            sv_files = glob.glob(os.path.join(self.annotated_dir, "*.sv"))
            if not sv_files:
                print(f"⚠️ 数据一致性检查：annotated 目录为空，但 sum_gj.dat 存在")
                print(f"   尝试恢复 annotated 报告...")
                if self._restore_annotated_if_needed():
                    print(f"✅ 已恢复 annotated 报告")
                    return True
                else:
                    print(f"❌ 恢复失败")
                    return False
            
            # 检查文件修改时间（粗略的一致性检查）
            sum_dat_mtime = os.path.getmtime(self.sum_dat_file)
            # 获取 annotated 目录中最新的文件修改时间
            latest_annotated_mtime = max(
                (os.path.getmtime(f) for f in sv_files[:100]),  # 只检查前100个文件
                default=0
            )
            
            # 如果 annotated 文件比 sum_gj.dat 旧很多（超过1小时），可能不同步
            time_diff = sum_dat_mtime - latest_annotated_mtime
            if time_diff > 3600:  # 1小时
                print(f"⚠️ 数据一致性检查：annotated 文件可能过期（比 sum_gj.dat 旧 {time_diff/3600:.1f} 小时）")
                print(f"   建议重新生成 annotated 报告")
                return False
            
            return True
        except Exception as e:
            print(f"⚠️ 数据一致性检查失败: {e}")
            return False

    def get_summary(self) -> dict:
        """获取覆盖率摘要"""
        module_stats = self.count_uncovered_by_module()
        total = sum(module_stats.values())
        
        return {
            "total_uncovered": total,
            "module_count": len(module_stats),
            "top_uncovered_modules": sorted(
                module_stats.items(), 
                key=lambda x: x[1], 
                reverse=True
            )[:10]
        }


def get_global_uncovered_count(annotated_dir: str, prefix: str = "%000000") -> int:
    """
    快速统计全局未覆盖代码行数（不创建 manager 对象）
    """
    total = 0
    sv_files = glob.glob(os.path.join(annotated_dir, "*.sv"))
    
    for sv_file in sv_files:
        try:
            with open(sv_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if prefix in line:
                        if 'PRINTF_COND' not in line and '$fwrite' not in line:
                            total += 1
        except:
            pass
    
    return total


# 测试代码
if __name__ == "__main__":
    manager = GlobalCoverageManager(
        project_root="/root/XiangShan",
        annotated_dir="/root/XiangShan/logs/annotated"
    )
    
    summary = manager.get_summary()
    print(f"\n📊 覆盖率摘要:")
    print(f"   总未覆盖行数: {summary['total_uncovered']}")
    print(f"   模块数量: {summary['module_count']}")
    print(f"   Top 10 未覆盖模块:")
    for module, count in summary['top_uncovered_modules']:
        print(f"      {module}: {count} 行")
