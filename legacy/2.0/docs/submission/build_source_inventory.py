#!/usr/bin/env python3
"""Inventory project documents and group copied worktrees/releases by logical path."""
from __future__ import annotations

import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[2]
BASE = REPO.parent
OUT = Path(__file__).resolve().parent
EXTS = {'.md', '.mdx', '.docx', '.pdf', '.tex'}
SKIP = {'.git', '.venv', 'node_modules', 'vendor', 'third_party', 'data', 'runtime', 'dist', 'build', '.pytest_cache'}


def files(root: Path):
    if not root.exists():
        return []
    proc = subprocess.run(['rg', '--files', '--hidden', *sum((['-g', f'!{s}'] for s in SKIP), []), str(root)], capture_output=True, text=True)
    return sorted(Path(s) for s in proc.stdout.splitlines() if Path(s).suffix.lower() in EXTS)


def extract(p: Path):
    if p.suffix == '.docx':
        with ZipFile(p) as z:
            root = ET.fromstring(z.read('word/document.xml'))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        return '\n'.join(''.join(t.text or '' for t in para.findall('.//w:t', ns)) for para in root.findall('.//w:p', ns))
    if p.suffix == '.pdf':
        result = subprocess.run(['pdftotext', str(p), '-'], capture_output=True, text=True)
        return result.stdout
    return p.read_text(encoding='utf-8', errors='replace')


def role(path: str):
    if '.TreeWork/' in path:
        return '阶段记录；用于还原演进，不单独证明当前产品完成'
    if any(s in path for s in ['docs/refactor/', 'dududa20-', 'deploy/stacks/bot-astrbot']):
        return '历史方案与迁移证据；对应设计报告第 12 节'
    if 'docs/research/' in path or 'docs/reviews/' in path:
        return '研究或评审结论；对应第 5—12 节，按日期复核'
    if 'docs/design/' in path or '/architecture/' in path:
        return '模块设计依据；对应第 3—9 节，采用前核对当前源码'
    if any(s in path for s in ['evals/', 'tests/', 'reports/', '100题', '100-question', '试用报告']):
        return '评测材料；对应第 12 节，保留数据来源与验证层级'
    if 'operations/' in path or '/deploy' in path:
        return '部署与运行记录；对应第 10—11 节'
    if 'services/' in path or 'astrbot-plugins/' in path:
        return '组件使用与扩展说明；对应第 4、7、10—11 节'
    if 'getting-started/' in path or '/foundations/' in path or '/reference/' in path:
        return '文档站教程与参考；汇入部署、术语和扩展说明'
    return '项目定位、开发说明或旧提交稿；汇入背景、架构和交付说明'


def main():
    records = []
    def add(p, key, family, primary=True):
        records.append({'path': str(p.relative_to(BASE)), 'logical_path': key, 'family': family, 'primary': primary, 'bytes': p.stat().st_size})

    for p in files(REPO):
        rel = p.relative_to(REPO).as_posix()
        if rel.startswith('docs/submission/'):
            continue
        add(p, 'dududa/' + rel, '主仓阶段记录' if rel.startswith('.TreeWork/') else '主仓文档')

    extra_roots = [
        ('dududa20-prototype', '历史原型'), ('dududa20-plugin', '历史插件'),
        ('dududa-submission', '原提交材料'), ('dududa-webui-review-2026-09-05', '外部试用报告'),
        ('mmdustc.top/apps/dududa-docs', '文档站'),
        ('dududa-state/web-deployments', '外部部署记录'),
    ]
    for rel, family in extra_roots:
        for p in files(BASE / rel):
            if '历史版本' not in p.parts:
                add(p, p.relative_to(BASE).as_posix(), family)
    for rel in ['嘟嘟哒群聊测试问题表-100题.md', 'dududa-recording-state/reports/benchmark-100.md', 'ustc-catalog-crawler/README.md', 'ustc-catalog-crawler/output/README.md', 'mmdustc.top/deploy/stacks/bot-astrbot-qq/DUDUDA.md']:
        p = BASE / rel
        if p.exists():
            add(p, rel, '周边资料与数据说明')

    snapshot_roots = list((BASE / '.treework-worktrees/dududa').glob('*'))
    snapshot_roots += list((BASE / 'dududa-state/releases').glob('*/source*'))
    for root in sorted(snapshot_roots):
        if not root.is_dir():
            continue
        for p in files(root):
            rel = p.relative_to(root).as_posix()
            if rel.startswith('docs/submission/'):
                continue
            add(p, 'dududa/' + rel, '工作树及发布副本', primary=False)

    groups = defaultdict(list)
    for r in records:
        groups[r['logical_path']].append(r)
    entries = []
    for key, copies in sorted(groups.items()):
        primary = next((r for r in copies if r['primary']), copies[0])
        p = BASE / primary['path']
        text = extract(p)
        headings = re.findall(r'^#{1,3}\s+(.+)$', text, re.M)
        fronttitle = re.search(r'^title:\s*[\"\']?(.+?)\s*[\"\']?$', text, re.M)
        title = headings[0] if headings else (fronttitle.group(1) if fronttitle else next((s.strip() for s in text.splitlines() if s.strip()), p.stem))
        # Titles and topic headings only: private runtime content is never merged.
        entries.append({'logical_path': key, 'title': title[:140], 'topics': headings[1:7], 'family': primary['family'], 'use': role(key), 'locations': [r['path'] for r in copies], 'primary': primary['primary']})

    result = {'date': '2026-09-06', 'scope': 'Code/dududa 与项目相关的原型、文档站、提交稿、评测及工作树/发布文档副本', 'physical_documents': len(records), 'logical_documents': len(entries), 'primary_documents': sum(r['primary'] for r in records), 'family_counts': dict(Counter(r['family'] for r in records)), 'entries': entries}
    (OUT / 'source-inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    lines = ['# 本地文档汇总与来源索引', '', '整理日期：2026-09-06。范围为嘟嘟哒主仓及与该作品直接相关的本地资料。', '', f"扫描到 **{len(records)} 份物理文档**，按逻辑路径归并为 **{len(entries)} 个文档条目**；其中当前主仓及独立来源文档 {result['primary_documents']} 份。副本完整位置保存在 `source-inventory.json` 的 `locations` 字段。", '', '## 汇总方法与范围', '', '- 主报告按场景、架构、模块、接口、部署、验证与演进组织内容，避免按开发时间逐篇粘贴。', '- 主仓源码与已存运行结果用于判断本次实现状态；设计、研究、原型和阶段记录分别保留其历史含义。', '- 工作树和发布快照按逻辑路径合并。下方列出当前来源及历史独有条目，JSON 保留每个副本位置；旧副本不能覆盖当前实现。', '- 原提交 PDF/Word 作为改写输入；它们与 Markdown 源稿存在内容重复。', '- 排除凭据、登录态、私有运行配置、聊天数据库、第三方依赖文档、自动生成数据条目，以及与作品无关的个人网站。培养方案数据集保留 README，不逐条计作设计文档。', '- 本目录新生成报告不计入原始资料数量。无法读取的私有 runtime 目录不属于技术文档扫描范围。', '', '## 主题整合结果', '', '| 主题 | 归纳结论 | 报告位置 |', '| --- | --- | --- |', '| 产品与场景 | 以群聊参与为交互形态，以课程、活动、教务、通知、出行和协作为实际任务 | 第 1、2、4 节 |', '| 核心设计 | 平台事实、语义感知、社交策略、模型路由、能力执行、表达和投递各负其责 | 第 3、5—9 节 |', '| 能力接入 | 五类 MCP 业务服务与校车本地能力构成六类校园服务；可选服务和独立插件分开说明 | 第 4、7 节 |', '| 研究与演进 | 作用域优先记忆、有限主动行为与在线学习研究提供后续路线；组件/离线实现不能替代聊天闭环 | 第 8、13 节 |', '| 工程与运行 | Web 与 QQ 共享 Runtime，独立 MCP worker 解决版本隔离，状态与源码分离 | 第 3、9—11 节 |', '| 评测与试用 | 离线流程、真实预览、原子工具测试、模拟入站和实际 QQ 投递按证据范围报告 | 第 12 节 |', '', '## 文档明细', '']
    for family in sorted({e['family'] for e in entries}):
        lines.extend([f'### {family}', ''])
        for e in (x for x in entries if x['family'] == family):
            topic = '；'.join(e['topics'][:5]) or '见标题及同目录说明'
            loc = e['locations'][0]
            lines.extend([f"- **{e['title'].replace('|', '/')}** — `{e['logical_path']}`", f"  议题：{topic}。{e['use']}。本地副本 {len(e['locations'])} 份。"])
        lines.append('')
    (OUT / '本地文档汇总.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'entries'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
