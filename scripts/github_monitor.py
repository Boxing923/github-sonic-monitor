#!/usr/bin/env python3
"""
GitHub 活动监控脚本 - GitHub Actions 版本
支持增量扫描和缓存机制
"""

import json
import os
import sys
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

# ============ 配置 ============
CONFIG = {
    "star_threshold": int(os.getenv("STAR_THRESHOLD", "50")),
    "extra_repos": os.getenv("EXTRA_REPOS", "sonic-net/sonic-platform-daemons").split(","),
    "dingtalk_folder": os.getenv("DINGTALK_FOLDER", "gwva2dxOW4vRkd9DUBnEx5ZoJbkz3BRL"),
    "orgs": ["sonic-net"],
    "extra_full_repos": ["FRRouting/frr"],
    "cache_dir": "cache",
    "reports_dir": "reports"
}

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# ============ 工具函数 ============
def github_api(url: str, params: dict = None) -> dict:
    """调用 GitHub API"""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "GitHub-SONiC-Monitor"
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    
    response = requests.get(f"{GITHUB_API}{url}", headers=headers, params=params, timeout=30)
    response.raise_for_status()
    return response.json()

def get_repos_by_stars(org: str, min_stars: int) -> List[Dict]:
    """获取组织下超过指定星数的仓库"""
    repos = []
    page = 1
    while True:
        data = github_api(f"/orgs/{org}/repos", {"per_page": 100, "page": page})
        if not data:
            break
        for repo in data:
            if repo.get("stargazers_count", 0) >= min_stars and not repo.get("archived", False):
                repos.append({
                    "name": repo["name"],
                    "full_name": repo["full_name"],
                    "stars": repo["stargazers_count"],
                    "url": repo["html_url"],
                    "updated_at": repo["updated_at"],
                    "default_branch": repo["default_branch"]
                })
        page += 1
        if len(data) < 100:
            break
    return repos

def get_repo_activity(repo_full_name: str, since: str) -> Dict:
    """获取仓库近期活动"""
    try:
        # 获取近期提交
        commits = github_api(f"/repos/{repo_full_name}/commits", {
            "since": since,
            "per_page": 10
        })
        
        # 获取近期 PR
        prs = github_api(f"/repos/{repo_full_name}/pulls", {
            "state": "all",
            "sort": "updated",
            "direction": "desc",
            "per_page": 10
        })
        
        # 筛选出指定时间后的 PR
        recent_prs = [pr for pr in prs if pr.get("updated_at", "") >= since]
        
        return {
            "commits": [
                {
                    "sha": c["sha"][:7],
                    "message": c["commit"]["message"].split("\n")[0][:80],
                    "author": c["commit"]["author"]["name"],
                    "date": c["commit"]["author"]["date"],
                    "url": c["html_url"],
                    "is_critical": any(kw in c["commit"]["message"].lower() 
                                      for kw in ["fix", "critical", "security", "breaking change", "vulnerability"])
                }
                for c in commits[:5]
            ],
            "prs": [
                {
                    "number": pr["number"],
                    "title": pr["title"][:80],
                    "author": pr["user"]["login"],
                    "state": pr["state"],
                    "updated_at": pr["updated_at"],
                    "url": pr["html_url"],
                    "is_critical": any(kw in pr["title"].lower() 
                                      for kw in ["fix", "critical", "security", "breaking change", "vulnerability"])
                }
                for pr in recent_prs[:5]
            ],
            "no_activity": len(commits) == 0 and len(recent_prs) == 0
        }
    except Exception as e:
        print(f"Error fetching {repo_full_name}: {e}")
        return {"no_activity": True, "error": str(e)}

# ============ 缓存管理 ============
class CacheManager:
    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.cache_file = os.path.join(cache_dir, "repo_cache.json")
        self.cache = self._load()

    def _load(self) -> Dict:
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {"last_scan": None, "repo_activities": {}}

    def save(self):
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f, indent=2)

    def should_scan_repo(self, repo: str, current_update: str) -> bool:
        """判断是否需要扫描该仓库（增量扫描）"""
        last = self.cache.get("repo_activities", {}).get(repo, {}).get("last_update")
        if last is None:
            return True
        return last != current_update

    def update_repo_timestamp(self, repo: str, timestamp: str):
        if "repo_activities" not in self.cache:
            self.cache["repo_activities"] = {}
        if repo not in self.cache["repo_activities"]:
            self.cache["repo_activities"][repo] = {}
        self.cache["repo_activities"][repo]["last_update"] = timestamp

# ============ 报告生成 ============
def generate_report(repos_data: List[Dict], scan_time: str) -> str:
    """生成 Markdown 报告"""
    report = f"""# 每日 GitHub 活动报告 — {scan_time[:10]}

**监控策略**: 50★以上全量监控 + sonic-platform-daemons 额外监控

**扫描仓库数**: {len(repos_data)} 个

**统计时间**: {scan_time}

---

"""

    # 分类展示
    categories = [
        ("🔴 紧急重点（Star > 1000）", lambda r: r.get("stars", 0) >= 1000),
        ("🟠 高度关注（Star 500-1000）", lambda r: 500 <= r.get("stars", 0) < 1000),
        ("🟡 正常关注（Star 100-500）", lambda r: 100 <= r.get("stars", 0) < 500),
        ("🟢 低优先级（Star < 100）", lambda r: r.get("stars", 0) < 100),
    ]

    for title, predicate in categories:
        repos = [r for r in repos_data if predicate(r)]
        if repos:
            report += f"# {title}\n\n"
            for repo in repos:
                report += format_repo_section(repo)

    return report

def format_repo_section(repo: Dict) -> str:
    """格式化单个仓库的展示"""
    name = repo.get("name", "Unknown")
    stars = repo.get("stars", 0)
    url = repo.get("url", "")
    activity = repo.get("activity", {})

    section = f"## [{name}]({url})（{stars} ★）\n\n"

    if activity.get("no_activity"):
        section += "【近期无活动】\n\n"
        return section

    prs = activity.get("prs", [])
    commits = activity.get("commits", [])

    if prs:
        section += "### PR 活动\n\n"
        for pr in prs[:5]:
            flag = "⚠️ " if pr.get("is_critical") else ""
            section += f"- {flag}[#{pr['number']}]({pr['url']}) {pr['title']} ({pr['state']})\n"
        section += "\n"

    if commits:
        section += "### 近期提交\n\n"
        for commit in commits[:3]:
            flag = "⚠️ " if commit.get("is_critical") else ""
            section += f"- {flag}[{commit['sha']}]({commit['url']}) {commit['message'][:60]}...\n"
        section += "\n"

    return section

# ============ 主函数 ============
def main():
    """主入口"""
    print("=" * 60)
    print("GitHub SONiC Monitor - GitHub Actions Version")
    print("=" * 60)
    
    now = datetime.utcnow()
    scan_time = now.isoformat()
    since = (now - timedelta(days=1)).isoformat()
    
    print(f"扫描时间: {scan_time}")
    print(f"时间范围: {since} ~ {scan_time}")
    print(f"星数阈值: {CONFIG['star_threshold']}")
    print("-" * 60)
    
    # 初始化缓存
    cache = CacheManager(CONFIG["cache_dir"])
    print(f"上次扫描: {cache.cache.get('last_scan', 'N/A')}")
    
    # 收集所有需要监控的仓库
    all_repos = []
    
    # 从组织获取高星仓库
    for org in CONFIG["orgs"]:
        print(f"\n获取 {org} 组织仓库（>={CONFIG['star_threshold']}★）...")
        repos = get_repos_by_stars(org, CONFIG["star_threshold"])
        print(f"  找到 {len(repos)} 个仓库")
        all_repos.extend(repos)
    
    # 添加额外监控的仓库
    for repo_full in CONFIG["extra_repos"]:
        if "/" in repo_full:
            try:
                data = github_api(f"/repos/{repo_full}")
                all_repos.append({
                    "name": data["name"],
                    "full_name": data["full_name"],
                    "stars": data["stargazers_count"],
                    "url": data["html_url"],
                    "updated_at": data["updated_at"],
                    "default_branch": data["default_branch"]
                })
                print(f"  添加额外监控: {repo_full}")
            except Exception as e:
                print(f"  无法获取 {repo_full}: {e}")
    
    # 添加 FRRouting/frr
    for repo_full in CONFIG["extra_full_repos"]:
        try:
            data = github_api(f"/repos/{repo_full}")
            all_repos.append({
                "name": data["name"],
                "full_name": data["full_name"],
                "stars": data["stargazers_count"],
                "url": data["html_url"],
                "updated_at": data["updated_at"],
                "default_branch": data["default_branch"]
            })
            print(f"  添加: {repo_full}")
        except Exception as e:
            print(f"  无法获取 {repo_full}: {e}")
    
    # 去重并排序
    seen = set()
    unique_repos = []
    for repo in all_repos:
        if repo["full_name"] not in seen:
            seen.add(repo["full_name"])
            unique_repos.append(repo)
    
    unique_repos.sort(key=lambda x: x["stars"], reverse=True)
    
    print(f"\n总计监控仓库: {len(unique_repos)} 个")
    print("-" * 60)
    
    # 扫描每个仓库的活动
    repos_with_activity = []
    for repo in unique_repos:
        print(f"\n扫描: {repo['full_name']} ({repo['stars']}★)")
        
        # 增量扫描检查
        if not cache.should_scan_repo(repo["full_name"], repo["updated_at"]):
            print("  [缓存命中] 无更新，跳过")
            continue
        
        activity = get_repo_activity(repo["full_name"], since)
        repo["activity"] = activity
        repos_with_activity.append(repo)
        
        # 更新缓存
        cache.update_repo_timestamp(repo["full_name"], repo["updated_at"])
        
        if activity.get("no_activity"):
            print("  无活动")
        else:
            print(f"  PR: {len(activity.get('prs', []))} 个")
            print(f"  Commit: {len(activity.get('commits', []))} 个")
    
    # 保存缓存
    cache.cache["last_scan"] = scan_time
    cache.save()
    
    # 生成报告
    print("\n" + "=" * 60)
    print("生成报告...")
    report = generate_report(repos_with_activity, scan_time)
    
    # 保存报告
    os.makedirs(CONFIG["reports_dir"], exist_ok=True)
    report_file = os.path.join(CONFIG["reports_dir"], f"report_{scan_time[:10]}.md")
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"报告已保存: {report_file}")
    
    # 输出摘要
    active_count = len([r for r in repos_with_activity if not r.get("activity", {}).get("no_activity", True)])
    print(f"\n摘要:")
    print(f"  扫描仓库: {len(repos_with_activity)}")
    print(f"  活跃仓库: {active_count}")
    print(f"  无活动: {len(repos_with_activity) - active_count}")
    print("=" * 60)

if __name__ == "__main__":
    main()
