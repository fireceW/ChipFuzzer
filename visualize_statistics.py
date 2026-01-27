#!/usr/bin/env python3
"""
统计可视化脚本
从统计数据 JSON 文件生成曲线图，展示：
1. LLM 生成次数
2. 模拟器成功执行次数
3. 覆盖率增长曲线
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False


def load_statistics(json_file):
    """加载统计数据"""
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def plot_statistics(stats_data, output_file=None):
    """生成统计图表"""
    # 创建图表
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle('ChipFuzzer 统计报告', fontsize=16, fontweight='bold')
    
    # 1. LLM 生成次数和模拟器成功执行次数（柱状图）
    ax1 = axes[0, 0]
    modules = []
    llm_counts = []
    emulator_counts = []
    
    for module_data in stats_data.get("modules", []):
        module_name = module_data.get("module_name", "unknown")
        module_stats = module_data.get("statistics", {})
        modules.append(module_name)
        llm_counts.append(module_stats.get("llm_generation_count", 0))
        emulator_counts.append(module_stats.get("emulator_success_count", 0))
    
    x = range(len(modules))
    width = 0.35
    
    ax1.bar([i - width/2 for i in x], llm_counts, width, label='LLM 生成次数', color='#4A90E2')
    ax1.bar([i + width/2 for i in x], emulator_counts, width, label='模拟器成功执行次数', color='#50C878')
    
    ax1.set_xlabel('模块')
    ax1.set_ylabel('次数')
    ax1.set_title('LLM 生成次数 vs 模拟器成功执行次数（按模块）')
    ax1.set_xticks(x)
    ax1.set_xticklabels(modules, rotation=45, ha='right')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # 2. 总体统计（饼图）
    ax2 = axes[0, 1]
    summary = stats_data.get("summary", {})
    total_llm = summary.get("total_llm_generations", 0)
    total_emulator = summary.get("total_emulator_success", 0)
    
    if total_llm > 0 or total_emulator > 0:
        labels = ['LLM 生成', '模拟器成功执行']
        sizes = [total_llm, total_emulator]
        colors = ['#4A90E2', '#50C878']
        
        ax2.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
        ax2.set_title('总体统计分布')
    else:
        ax2.text(0.5, 0.5, '暂无数据', ha='center', va='center', transform=ax2.transAxes)
        ax2.set_title('总体统计分布')
    
    # 3. 覆盖率增长曲线（时间序列）
    ax3 = axes[1, 0]
    all_coverage_data = []
    
    for module_data in stats_data.get("modules", []):
        module_stats = module_data.get("statistics", {})
        coverage_data = module_stats.get("coverage_data", [])
        all_coverage_data.extend(coverage_data)
    
    # 按时间排序
    all_coverage_data.sort(key=lambda x: x.get("timestamp", 0))
    
    if all_coverage_data:
        timestamps = [datetime.fromtimestamp(d["timestamp"]) for d in all_coverage_data]
        coverage_percentages = [d["coverage_percentage"] for d in all_coverage_data]
        
        ax3.plot(timestamps, coverage_percentages, marker='o', linestyle='-', linewidth=2, markersize=4, color='#E74C3C')
        ax3.set_xlabel('时间')
        ax3.set_ylabel('覆盖率 (%)')
        ax3.set_title('覆盖率增长曲线')
        ax3.grid(True, alpha=0.3)
        
        # 格式化 x 轴时间
        ax3.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        ax3.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax3.xaxis.get_majorticklabels(), rotation=45, ha='right')
    else:
        ax3.text(0.5, 0.5, '暂无覆盖率数据', ha='center', va='center', transform=ax3.transAxes)
        ax3.set_title('覆盖率增长曲线')
    
    # 4. 未覆盖代码行数变化曲线
    ax4 = axes[1, 1]
    
    if all_coverage_data:
        uncovered_lines = [d["uncovered_lines"] for d in all_coverage_data]
        
        ax4.plot(timestamps, uncovered_lines, marker='s', linestyle='-', linewidth=2, markersize=4, color='#9B59B6')
        ax4.set_xlabel('时间')
        ax4.set_ylabel('未覆盖代码行数')
        ax4.set_title('未覆盖代码行数变化曲线')
        ax4.grid(True, alpha=0.3)
        
        # 格式化 x 轴时间
        ax4.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        ax4.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax4.xaxis.get_majorticklabels(), rotation=45, ha='right')
        
        # 反转 y 轴，使下降表示改进
        ax4.invert_yaxis()
    else:
        ax4.text(0.5, 0.5, '暂无数据', ha='center', va='center', transform=ax4.transAxes)
        ax4.set_title('未覆盖代码行数变化曲线')
    
    plt.tight_layout()
    
    # 保存图表
    if output_file:
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        print(f"📊 图表已保存: {output_file}")
    else:
        plt.show()


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python visualize_statistics.py <statistics_json_file> [output_image_file]")
        print("示例: python visualize_statistics.py GJ_log/statistics_20260127_120000.json output.png")
        sys.exit(1)
    
    json_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not os.path.exists(json_file):
        print(f"❌ 文件不存在: {json_file}")
        sys.exit(1)
    
    try:
        stats_data = load_statistics(json_file)
        plot_statistics(stats_data, output_file)
    except Exception as e:
        print(f"❌ 生成图表时出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
