"""
Global coverage management module
Responsible for counting and updating the code coverage of the entire project, not just a single module
"""

import os
import glob
import re
import subprocess
import json
from typing import Tuple, List, Optional, Dict

# Module groups that require separate statistics
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
    Manage global coverage statistics
    - Traverse all .sv files in the annotated directory
    - Count the number of uncovered lines of code for all modules
    - Consolidate coverage data and update reports
    """

    def __init__(self, project_root: str, annotated_dir: str, sum_dat_file: str = None):
        """
        parameter:
            project_root: project root directory (such as /root/XiangShan)
            annotated_dir: annotated directory path (such as /root/XiangShan/logs_testcase/annotated)
            sum_dat_file: cumulative coverage file path (default is project_root/sum_gj.dat)
        """
        self.project_root = project_root
        self.annotated_dir = annotated_dir
        self.sum_dat_file = sum_dat_file or os.path.join(project_root, "sum_gj.dat")
        
        # Statistical baseline during initialization
        self.baseline_uncovered_count = 0
        self.baseline_uncovered_lines = []
        
        # Whether the tag is in Fresh mode (by checking if the annotated directory is empty and sum_gj.dat does not exist)
        # If the annotated directory is empty and sum_gj.dat does not exist, it means Fresh mode
        annotated_empty = not os.path.exists(self.annotated_dir) or \
                         (os.path.exists(self.annotated_dir) and 
                          len(glob.glob(os.path.join(self.annotated_dir, "*.sv"))) == 0)
        sum_dat_missing = not os.path.exists(self.sum_dat_file) or os.path.getsize(self.sum_dat_file) == 0
        self.is_fresh_mode = annotated_empty and sum_dat_missing
        
        # debug log
        print(f"🔍 [GlobalCoverageManager.__init__] 初始化检查:")
        print(f"   annotated_dir: {self.annotated_dir}")
        print(f"   annotated_empty: {annotated_empty}")
        print(f"   sum_dat_file: {self.sum_dat_file}")
        print(f"   sum_dat_missing: {sum_dat_missing}")
        print(f"   is_fresh_mode: {self.is_fresh_mode}")
        
        # If the annotated directory is empty but sum_gj.dat exists, restore the annotated report first
        # This usually happens when the annotated directory is accidentally emptied in continue mode
        # But in Fresh mode, it should not be restored (because sum_gj.dat should have been deleted)
        if not self.is_fresh_mode:
            self._restore_annotated_if_needed()
        
        self._update_baseline()
    
    def _restore_annotated_if_needed(self) -> bool:
        """
        Restore annotated reports from sum_gj.dat if needed
        
        return:
            Is the recovery successful:
        """
        if os.path.exists(self.sum_dat_file) and os.path.getsize(self.sum_dat_file) > 0:
            # Check if the annotated directory exists and has files
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
        """Update baseline statistics"""
        # If it is Fresh mode, the baseline should remain at 0 and no statistics will be collected.
        if getattr(self, 'is_fresh_mode', False):
            print(f"📊 Fresh 模式：基线保持为 0（等待首次测试后设置新基线）")
            self.baseline_uncovered_count = 0
            self.baseline_uncovered_lines = []
            return
        
        # If the annotated directory exists and has files, the baseline will be counted.
        # If the directory is empty (fresh mode has just been reset), the baseline remains at 0 and will be set again after the first test.
        if os.path.exists(self.annotated_dir):
            sv_files = glob.glob(os.path.join(self.annotated_dir, "*.sv"))
            if sv_files:  # Statistics are only counted if there are files in the directory
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
        Reset coverage files and start a new testing cycle
        
        parameter:
            backup: whether to back up the old sum_gj.dat file
            reset_annotated: whether to reset the annotated directory
            
        return:
            Is the reset successful:
        """
        import shutil
        import time
        
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            
            # 1. Back up and delete sum_gj.dat
            if os.path.exists(self.sum_dat_file):
                if backup:
                    backup_file = f"{self.sum_dat_file}.backup_{timestamp}"
                    shutil.copy2(self.sum_dat_file, backup_file)
                    print(f"📦 已备份旧覆盖率文件: {backup_file}")
                
                os.remove(self.sum_dat_file)
                print(f"🗑️ 已删除旧覆盖率文件: {self.sum_dat_file}")
            
            # 2. Reset the annotated directory (clear the contents of the global accumulation directory)
            if reset_annotated and os.path.exists(self.annotated_dir):
                if backup:
                    backup_dir = f"{self.annotated_dir}.backup_{timestamp}"
                    if os.path.exists(backup_dir):
                        shutil.rmtree(backup_dir)
                    shutil.copytree(self.annotated_dir, backup_dir)
                    print(f"📦 已备份旧 annotated 目录: {backup_dir}")
                
                # Empty the directory contents (but keep the directory itself)
                for item in os.listdir(self.annotated_dir):
                    item_path = os.path.join(self.annotated_dir, item)
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                print(f"🗑️ 已清空 annotated 目录: {self.annotated_dir}")
            
            # 3. Delete coverage.info (let it regenerate in new tests)
            coverage_info_file = os.path.join(self.project_root, "coverage.info")
            if os.path.exists(coverage_info_file):
                if backup:
                    backup_coverage = f"{coverage_info_file}.backup_{timestamp}"
                    shutil.copy2(coverage_info_file, backup_coverage)
                    print(f"📦 已备份旧 coverage.info: {backup_coverage}")
                os.remove(coverage_info_file)
                print(f"🗑️ 已删除旧 coverage.info")
            
            # In Fresh mode, force reset baseline to 0
            # Do not call _update_baseline() as there may be residual files in the annotated directory
            self.baseline_uncovered_count = 0
            self.baseline_uncovered_lines = []
            # Marked as Fresh mode
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
        Get current coverage information
        
        return:
            A dictionary containing coverage statistics
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

    def get_total_coverage_from_genhtml(self, use_cache=True) -> dict:
        """
        Get total coverage percentage via genhtml
        
        parameter:
            use_cache: If parsing fails, whether to use the last valid value (default True)
        
        return:
            A dictionary containing coverage percentages
        """
        import re
        import time
        coverage_info_file = os.path.join(self.project_root, "coverage.info")
        
        # If coverage.info does not exist, try to generate it from sum_gj.dat
        if not os.path.exists(coverage_info_file):
            # Check if it is Fresh mode (sum_gj.dat does not exist either)
            if not os.path.exists(self.sum_dat_file) or os.path.getsize(self.sum_dat_file) == 0:
                return {"coverage_percentage": 0.0, "covered": 0, "total": 0, "status": "no_data", "message": "Fresh 模式：等待首次测试数据"}
            
            # If not Fresh mode, try to generate coverage.info from sum_gj.dat
            print(f"⚠️ coverage.info 不存在，尝试从 sum_gj.dat 生成...")
            if self.update_coverage_info():
                print(f"✅ 已从 sum_gj.dat 生成 coverage.info")
                # Wait for file writing to complete
                time.sleep(0.5)
            else:
                return {"coverage_percentage": 0.0, "covered": 0, "total": 0, "status": "error", "message": "无法从 sum_gj.dat 生成 coverage.info"}
        
        # Check the file status: Make sure the file exists and is the correct size
        if not os.path.exists(coverage_info_file):
            if use_cache and hasattr(self, '_last_valid_coverage'):
                print(f"⚠️ coverage.info 不存在，使用上次有效值: {self._last_valid_coverage['coverage_percentage']:.2f}%")
                return self._last_valid_coverage
            return {"coverage_percentage": 0.0, "covered": 0, "total": 0, "status": "error", "message": "coverage.info 不存在"}
        
        file_size = os.path.getsize(coverage_info_file)
        if file_size == 0:
            if use_cache and hasattr(self, '_last_valid_coverage'):
                print(f"⚠️ coverage.info 为空，使用上次有效值: {self._last_valid_coverage['coverage_percentage']:.2f}%")
                return self._last_valid_coverage
            return {"coverage_percentage": 0.0, "covered": 0, "total": 0, "status": "error", "message": "coverage.info 文件为空"}
        
        # Wait for the file to stabilize (if the file has just been updated, wait to make sure the write is complete)
        try:
            mtime1 = os.path.getmtime(coverage_info_file)
            time.sleep(0.3)  # wait 300ms
            mtime2 = os.path.getmtime(coverage_info_file)
            if mtime1 != mtime2:
                # The file is still being updated, please wait a little longer.
                time.sleep(0.5)
        except:
            pass
        
        # Retry mechanism: retry up to 2 times
        max_retries = 2
        last_error = None
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    # Wait before retrying
                    time.sleep(1)
                    print(f"🔄 重试 genhtml 解析（第 {attempt + 1} 次）...")
                
                result = subprocess.run(
                    ["genhtml", "coverage.info", "--output-directory", "coverage_gj"],
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                
                output = result.stdout + result.stderr
                
                # Parse "Overall coverage rate: lines......: 72.2% (463483 of 642121 lines)"
                match = re.search(r'lines\.+:\s*([\d.]+)%\s*\((\d+)\s+of\s+(\d+)\s+lines\)', output)
                
                if match:
                    percentage = float(match.group(1))
                    covered = int(match.group(2))
                    total = int(match.group(3))
                    result_data = {
                        "coverage_percentage": percentage,  # Use coverage_percentage uniformly
                        "percentage": percentage,  # Stay backwards compatible
                        "covered": covered,
                        "total": total,
                        "status": "ok"
                    }
                    # Save as valid value
                    self._last_valid_coverage = result_data
                    return result_data
                else:
                    last_error = "无法解析 genhtml 输出"
                    # Log output for debugging (only log the last 500 characters to avoid making it too long)
                    debug_output = output[-500:] if len(output) > 500 else output
                    print(f"⚠️ genhtml 输出解析失败（尝试 {attempt + 1}/{max_retries}）")
                    print(f"   genhtml 输出（最后 500 字符）: {debug_output}")
                    
            except subprocess.TimeoutExpired:
                last_error = "genhtml 执行超时"
                print(f"⚠️ genhtml 执行超时（尝试 {attempt + 1}/{max_retries}）")
            except Exception as e:
                last_error = f"执行异常: {e}"
                print(f"⚠️ genhtml 执行异常（尝试 {attempt + 1}/{max_retries}）: {e}")
        
        # All retries fail, use cache or return an error
        if use_cache and hasattr(self, '_last_valid_coverage'):
            print(f"⚠️ genhtml 解析失败，使用上次有效值: {self._last_valid_coverage['coverage_percentage']:.2f}%")
            return {
                **self._last_valid_coverage,
                "status": "parse_error_using_cache",
                "warning": f"genhtml 解析失败（{last_error}），使用上次有效值"
            }
        else:
            return {"coverage_percentage": 0.0, "percentage": 0.0, "covered": 0, "total": 0, "status": "parse_error", "message": last_error or "无法解析 genhtml 输出"}

    def print_total_coverage(self, title: str = "总覆盖率") -> dict:
        """
        Print total coverage information
        
        parameter:
            title: the displayed title
            
        return:
            coverage information dictionary
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
        Get coverage statistics for a single module
        
        parameter:
            module_name: module name (without .sv suffix)
            
        return:
            A dictionary containing coverage statistics
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
                    # Skip empty lines and plain comment lines
                    if not stripped or stripped.startswith('//'):
                        continue
                    
                    # Check coverage tags (use regular expression matching, more accurate)
                    if '%' in stripped:
                        coverage_markers = re.findall(r'%(\d{6})', stripped)
                        if coverage_markers:
                            total_lines += 1
                            # Check if there is a non-zero coverage flag (indicating coverage)
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
        Get coverage statistics for a module group
        
        parameter:
            group_name: module group name (such as "L2"), if None, all groups will be counted
            
        return:
            Dictionary containing coverage of each module
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
        Print coverage statistics for module groups
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
                    # Select color markers based on coverage
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
        Count the uncovered code lines of all .sv files in the annotated directory
        
        return:
            Contains a list of all uncovered lines of code
        """
        all_uncovered = []
        
        # Check if directory exists
        if not os.path.exists(self.annotated_dir):
            print(f"⚠️ annotated 目录不存在: {self.annotated_dir}")
            return all_uncovered
        
        # Iterate through all .sv files
        sv_files = glob.glob(os.path.join(self.annotated_dir, "*.sv"))
        
        for sv_file in sv_files:
            try:
                with open(sv_file, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        stripped = line.strip()
                        # Skip empty lines and plain comment lines
                        if not stripped or stripped.startswith('//'):
                            continue
                        
                        # Use regular expressions to match coverage tags to ensure accuracy
                        if '%' in stripped:
                            coverage_markers = re.findall(r'%(\d{6})', stripped)
                            # If all tags are 000000, it means they are not covered
                            if coverage_markers and all(marker == '000000' for marker in coverage_markers):
                                # Filter out all printing-related lines of code (including $fwrite and its continuation lines)
                                if ('PRINTF_COND' not in stripped and 
                                    '$fwrite' not in stripped and
                                    'io_timer' not in stripped):  # io_timer is usually a parameter of $fwrite
                                    all_uncovered.append(stripped)
            except Exception as e:
                print(f"⚠️ 读取文件失败 {sv_file}: {e}")
        
        return all_uncovered

    def count_uncovered_by_module(self, prefix: str = "%000000") -> dict:
        """
        Count the number of uncovered lines of code by module
        
        return:
            Dictionary of {module name: number of lines not covered}
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
                        # Skip empty lines and plain comment lines
                        if not stripped or stripped.startswith('//'):
                            continue
                        
                        # Implementation note.
                        if '%' in stripped:
                            coverage_markers = re.findall(r'%(\d{6})', stripped)
                            # If all tags are 000000, it means they are not covered
                            if coverage_markers and all(marker == '000000' for marker in coverage_markers):
                                # Filter out all printing related lines of code
                                if ('PRINTF_COND' not in stripped and 
                                    '$fwrite' not in stripped and
                                    'io_timer' not in stripped):  # io_timer is usually a parameter of $fwrite
                                    count += 1
                module_stats[module_name] = count
            except Exception as e:
                print(f"⚠️ 读取文件失败 {sv_file}: {e}")
        
        return module_stats

    def merge_coverage_dat(self, new_dat_file: str) -> bool:
        """
        Merge new .dat file into cumulative coverage file
        
        parameter:
            new_dat_file: Newly generated coverage.dat file path
            
        return:
            Is it successful:
        """
        # Implementation note.
        if not os.path.exists(new_dat_file):
            print(f"❌ 覆盖率文件不存在: {new_dat_file}")
            return False
        
        # Check new file size
        new_file_size = os.path.getsize(new_dat_file)
        if new_file_size == 0:
            print(f"⚠️ 覆盖率文件为空: {new_dat_file}")
            return False
        
        try:
            if os.path.exists(self.sum_dat_file) and os.path.getsize(self.sum_dat_file) > 0:
                # Check old file size
                old_file_size = os.path.getsize(self.sum_dat_file)
                print(f"📊 合并覆盖率数据: 旧文件 {old_file_size / 1024:.1f} KB + 新文件 {new_file_size / 1024:.1f} KB")
                # Merge existing and new
                cmd = f"verilator_coverage -write {self.sum_dat_file} {self.sum_dat_file} {new_dat_file}"
            else:
                # The first time (Fresh mode or first run), copy directly
                print(f"📊 首次创建累积覆盖率文件: {new_file_size / 1024:.1f} KB")
                cmd = f"verilator_coverage -write {self.sum_dat_file} {new_dat_file}"
            
            print(f"📌 [阶段] 正在合并 sum_gj.dat（verilator_coverage -write），请稍候...")
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
            
            # Verify merged files
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
        """update_annotated_report documentation."""
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
        Update coverage.info file (used by tools like genhtml)
        """
        if not os.path.exists(self.sum_dat_file):
            return False
        
        try:
            cmd = f"verilator_coverage -write-info coverage.info {self.sum_dat_file}"
            
            print(f"📌 [阶段] 正在更新 coverage.info，请稍候...")
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
        Check whether global coverage has improved after running the test
        
        parameter:
            new_dat_file: Newly generated coverage.dat file path
            
        return:
            (Is there any improvement, number of lines reduced, list of newly covered lines of code)
        """
        print(f"🔄 正在更新全局覆盖率数据...")
        print(f"   当前基线: {self.baseline_uncovered_count} 行未覆盖")
        print(f"   Fresh 模式: {getattr(self, 'is_fresh_mode', False)}")
        
        # 1. Incorporate new coverage data
        if not self.merge_coverage_dat(new_dat_file):
            print(f"❌ 合并覆盖率数据失败")
            return False, 0, []
        
        # 2. Update annotated report
        if not self.update_annotated_report():
            print(f"❌ 更新 annotated 报告失败")
            return False, 0, []
        
        print(f"✅ 全局 annotated 目录已更新: {self.annotated_dir}")
        
        # 3. Update coverage.info
        if self.update_coverage_info():
            print(f"✅ coverage.info 已更新")
        
        # 4. Recount the uncovered code lines
        new_uncovered_lines = self.get_all_uncovered_lines()
        new_uncovered_count = len(new_uncovered_lines)
        print(f"   新统计: {new_uncovered_count} 行未覆盖")
        
        # Special handling: if the baseline is 0 (fresh mode or first run), set the baseline with the current results
        # But you need to make sure that this is a real first run and not because the annotated directory was emptied.
        if self.baseline_uncovered_count == 0 and new_uncovered_count > 0:
            # If it is Fresh mode, set the baseline directly without trying to restore
            if getattr(self, 'is_fresh_mode', False):
                # Fresh mode: Sets the baseline directly without trying to restore from sum_gj.dat
                print(f"📊 Fresh 模式：首次统计全局覆盖率")
                print(f"   设置基线: {new_uncovered_count} 行未覆盖代码")
                print(f"   注意：这是首次测试后的基线，后续测试将以此为基础计算提升")
                self.baseline_uncovered_count = new_uncovered_count
                self.baseline_uncovered_lines = new_uncovered_lines
                # Mark Fresh mode has completed its first baseline setup
                self.is_fresh_mode = False
                # Setting the baseline for the first time, does not count as a "boost", returns False
                return False, 0, []
            
            # Check if sum_gj.dat exists and is not empty
            sum_dat_exists = os.path.exists(self.sum_dat_file) and os.path.getsize(self.sum_dat_file) > 0
            
            if not sum_dat_exists:
                # True first run (fresh mode), setting baseline
                print(f"📊 首次统计全局覆盖率，设置基线: {new_uncovered_count} 行未覆盖")
                self.baseline_uncovered_count = new_uncovered_count
                self.baseline_uncovered_lines = new_uncovered_lines
                # Setting the baseline for the first time, does not count as a "boost", returns False
                return False, 0, []
            else:
                # sum_gj.dat exists but the baseline is 0, indicating that the annotated directory may have been accidentally emptied in continue mode.
                # In this case, the annotated report should be regenerated from sum_gj.dat and then the baseline statistics
                # NOTE: This should not happen since recovery is already attempted in __init__
                # But if it happens, try recovery again
                print(f"⚠️ 基线为 0 但 sum_gj.dat 存在，尝试从 sum_gj.dat 恢复基线...")
                if self._restore_annotated_if_needed():
                    # Rebaseline
                    self.baseline_uncovered_lines = self.get_all_uncovered_lines()
                    self.baseline_uncovered_count = len(self.baseline_uncovered_lines)
                    print(f"📊 已恢复基线: {self.baseline_uncovered_count} 行未覆盖代码")
                else:
                    # Recovery fails, using current results as baseline (but logging a warning)
                    print(f"⚠️ 恢复失败，使用当前结果设置基线: {new_uncovered_count} 行未覆盖")
                    print(f"   警告：这可能导致基线不准确，建议检查 annotated 目录状态")
                    self.baseline_uncovered_count = new_uncovered_count
                    self.baseline_uncovered_lines = new_uncovered_lines
                return False, 0, []
        
        # 5. Calculate the difference
        reduced_count = self.baseline_uncovered_count - new_uncovered_count
        
        # Find newly covered rows (in old baseline but not in new statistics)
        new_uncovered_set = set(new_uncovered_lines)
        newly_covered = [
            line for line in self.baseline_uncovered_lines 
            if line not in new_uncovered_set
        ]
        
        # 6. Determine whether there is improvement (reduction in the number of uncovered rows = improvement in coverage)
        improved = new_uncovered_count < self.baseline_uncovered_count
        
        # Safety check: If the number of new uncovered rows is unusually large (much larger than the baseline), it may be a statistical error
        # The baseline is not updated in this case to avoid coverage appearing to drop.
        if self.baseline_uncovered_count > 0:
            if new_uncovered_count > self.baseline_uncovered_count * 1.1:
                print(f"⚠️ 警告：新未覆盖行数 ({new_uncovered_count}) 比基线 ({self.baseline_uncovered_count}) 大 10% 以上")
                print(f"   可能是统计错误或 annotated 目录数据不一致，保持基线不变")
                print(f"   建议检查 annotated 目录和 sum_gj.dat 是否同步")
                return False, 0, []
            
            # Extra check: if the number of new uncovered rows is greater than the baseline, but not more than 10%, log a warning but don't block
            if new_uncovered_count > self.baseline_uncovered_count:
                print(f"⚠️ 注意：新未覆盖行数 ({new_uncovered_count}) 比基线 ({self.baseline_uncovered_count}) 大")
                print(f"   这不应该发生，可能是数据不一致，但差异较小，继续处理")
        
        if improved:
            print(f"🎉 全局覆盖率提升！")
            print(f"   未覆盖代码: {self.baseline_uncovered_count} → {new_uncovered_count}")
            print(f"   减少了 {reduced_count} 行未覆盖代码")
            
            # Show some newly covered lines of code
            if newly_covered:
                print(f"   新覆盖的代码行 (前 10 行):")
                for i, line in enumerate(newly_covered[:10]):
                    # Intercept the display to avoid being too long
                    display_line = line[:80] + "..." if len(line) > 80 else line
                    print(f"   {i+1}. {display_line}")
                if len(newly_covered) > 10:
                    print(f"   还有 {len(newly_covered) - 10} 行...")
            
            # Update baseline (only update if there is actual improvement)
            self.baseline_uncovered_count = new_uncovered_count
            self.baseline_uncovered_lines = new_uncovered_lines
            
            # Verify data consistency: check if sum_gj.dat and annotated directories are in sync
            self._verify_data_consistency()
        else:
            if new_uncovered_count == self.baseline_uncovered_count:
                print(f"ℹ️ 全局覆盖率无变化: {new_uncovered_count} 行未覆盖 (基线: {self.baseline_uncovered_count})")
            else:
                # This shouldn't happen (already checked earlier)
                print(f"⚠️ 全局覆盖率异常: 新未覆盖行数 ({new_uncovered_count}) != 基线 ({self.baseline_uncovered_count})")
                print(f"   保持基线不变")
        
        return improved, reduced_count, newly_covered

    def _verify_data_consistency(self):
        """Verify data consistency: check if sum_gj.dat and annotated directories are in sync"""
        try:
            # Check if sum_gj.dat exists
            if not os.path.exists(self.sum_dat_file):
                print(f"⚠️ 数据一致性检查：sum_gj.dat 不存在")
                return False
            
            # Check if the annotated directory has files
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
            
            # Check file modification time (rough consistency check)
            sum_dat_mtime = os.path.getmtime(self.sum_dat_file)
            # Get the latest file modification time in the annotated directory
            latest_annotated_mtime = max(
                (os.path.getmtime(f) for f in sv_files[:100]),  # Only check first 100 files
                default=0
            )
            
            # If the annotated file is much older (more than 1 hour) than sum_gj.dat, it may be out of sync
            time_diff = sum_dat_mtime - latest_annotated_mtime
            if time_diff > 3600:  # 1 hour
                print(f"⚠️ 数据一致性检查：annotated 文件可能过期（比 sum_gj.dat 旧 {time_diff/3600:.1f} 小时）")
                print(f"   建议重新生成 annotated 报告")
                return False
            
            return True
        except Exception as e:
            print(f"⚠️ 数据一致性检查失败: {e}")
            return False

    def get_summary(self) -> dict:
        """Get coverage summary"""
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
    Quickly count the number of global uncovered lines of code (without creating a manager object)
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


# test code
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
