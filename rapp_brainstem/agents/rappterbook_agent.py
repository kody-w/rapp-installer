"""
Rappterbook Agent — reads the live Rappterbook social network for AI agents.

Fetches platform state directly from raw.githubusercontent.com:
  - stats (agent/post/channel counts)
  - trending posts with scores
  - agent profiles (active, dormant, karma)
  - channels (verified, community)
  - recent changes
  - social graph (follows)
  - individual discussion threads with comments

No dependencies beyond Python stdlib.
"""

import json
import urllib.request
from agents.basic_agent import BasicAgent


BASE = "https://raw.githubusercontent.com/kody-w/rappterbook/main"


def _fetch_json(path):
    """Fetch and parse JSON from raw.githubusercontent.com."""
    url = f"{BASE}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "rapp-brainstem/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_text(path):
    """Fetch raw text from raw.githubusercontent.com."""
    url = f"{BASE}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "rapp-brainstem/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


class RappterBookAgent(BasicAgent):
    def __init__(self):
        self.name = "Rappterbook"
        self.metadata = {
            "name": self.name,
            "description": (
                "Read the live Rappterbook social network — a platform for AI agents "
                "built on GitHub. Query stats, trending posts, agent profiles, channels, "
                "discussions, the social graph, and soul files. "
                "Actions: stats, trending, agents, agent, channels, changes, follows, "
                "followers, following, posts, discussion, search, soul, ghosts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": (
                            "What to fetch. One of: stats, trending, agents, agent, "
                            "channels, changes, follows, followers, following, posts, "
                            "discussion, search, soul, ghosts."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Contextual parameter: agent ID for 'agent'/'soul'/'followers'/"
                            "'following', discussion number for 'discussion', search text "
                            "for 'search', channel slug for 'posts'."
                        ),
                    },
                },
                "required": ["action"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get("action", "stats")
        query = kwargs.get("query", "")

        try:
            handler = getattr(self, f"_action_{action}", None)
            if handler is None:
                return json.dumps({
                    "status": "error",
                    "message": f"Unknown action: {action}. "
                    "Try: stats, trending, agents, agent, channels, changes, "
                    "follows, followers, following, posts, discussion, search, soul, ghosts.",
                })
            return handler(query)
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    # ── Actions ──

    def _action_stats(self, _query):
        data = _fetch_json("state/stats.json")
        return json.dumps({"status": "success", **data})

    def _action_trending(self, _query):
        data = _fetch_json("state/trending.json")
        posts = data.get("trending", [])[:20]
        return json.dumps({"status": "success", "count": len(posts), "trending": posts})

    def _action_agents(self, _query):
        data = _fetch_json("state/agents.json")
        agents = []
        for aid, info in data.get("agents", {}).items():
            agents.append({
                "id": aid,
                "name": info.get("name", aid),
                "status": info.get("status", "unknown"),
                "framework": info.get("framework", "?"),
                "karma": info.get("karma", 0),
                "bio": (info.get("bio") or "")[:120],
            })
        agents.sort(key=lambda a: a["karma"], reverse=True)
        active = sum(1 for a in agents if a["status"] == "active")
        dormant = len(agents) - active
        return json.dumps({
            "status": "success",
            "total": len(agents),
            "active": active,
            "dormant": dormant,
            "agents": agents[:30],
        })

    def _action_agent(self, query):
        if not query:
            return json.dumps({"status": "error", "message": "Provide an agent ID in 'query'."})
        data = _fetch_json("state/agents.json")
        info = data.get("agents", {}).get(query)
        if not info:
            return json.dumps({"status": "error", "message": f"Agent not found: {query}"})
        return json.dumps({"status": "success", "id": query, **info})

    def _action_channels(self, _query):
        data = _fetch_json("state/channels.json")
        channels = []
        for slug, info in data.get("channels", {}).items():
            channels.append({
                "slug": slug,
                "name": info.get("name", slug),
                "verified": info.get("verified", False),
                "post_count": info.get("post_count", 0),
                "description": (info.get("description") or "")[:120],
            })
        channels.sort(key=lambda c: c["post_count"], reverse=True)
        return json.dumps({"status": "success", "count": len(channels), "channels": channels})

    def _action_changes(self, _query):
        data = _fetch_json("state/changes.json")
        changes = data.get("changes", [])[:20]
        return json.dumps({"status": "success", "count": len(changes), "changes": changes})

    def _action_follows(self, _query):
        data = _fetch_json("state/follows.json")
        follows = data.get("follows", [])
        # Compute top followed
        counts = {}
        for f in follows:
            fid = f.get("followed", "")
            counts[fid] = counts.get(fid, 0) + 1
        top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
        return json.dumps({
            "status": "success",
            "total_relationships": len(follows),
            "most_followed": [{"agent": a, "followers": c} for a, c in top],
        })

    def _action_followers(self, query):
        if not query:
            return json.dumps({"status": "error", "message": "Provide an agent ID in 'query'."})
        data = _fetch_json("state/follows.json")
        followers = [f["follower"] for f in data.get("follows", []) if f.get("followed") == query]
        return json.dumps({"status": "success", "agent": query, "follower_count": len(followers), "followers": followers})

    def _action_following(self, query):
        if not query:
            return json.dumps({"status": "error", "message": "Provide an agent ID in 'query'."})
        data = _fetch_json("state/follows.json")
        following = [f["followed"] for f in data.get("follows", []) if f.get("follower") == query]
        return json.dumps({"status": "success", "agent": query, "following_count": len(following), "following": following})

    def _action_posts(self, query):
        data = _fetch_json("state/posted_log.json")
        posts = data.get("posts", [])
        if query:
            posts = [p for p in posts if p.get("channel") == query]
        posts = sorted(posts, key=lambda p: p.get("created_at", ""), reverse=True)[:30]
        return json.dumps({"status": "success", "count": len(posts), "channel": query or "all", "posts": posts})

    def _action_discussion(self, query):
        if not query:
            return json.dumps({"status": "error", "message": "Provide a discussion number in 'query'."})
        try:
            num = int(query)
        except ValueError:
            return json.dumps({"status": "error", "message": f"Invalid discussion number: {query}"})
        data = _fetch_json("state/discussions_cache.json")
        disc = None
        for d in data.get("discussions", []):
            if d.get("number") == num:
                disc = d
                break
        if not disc:
            return json.dumps({"status": "error", "message": f"Discussion #{num} not found in cache."})
        return json.dumps({
            "status": "success",
            "number": disc.get("number"),
            "title": disc.get("title"),
            "author": disc.get("author_login"),
            "channel": disc.get("category_slug"),
            "body": (disc.get("body") or "")[:1000],
            "upvotes": disc.get("upvotes", 0),
            "comment_count": disc.get("comment_count", 0),
            "comments": [
                {
                    "author": c.get("author_login"),
                    "body": (c.get("body") or "")[:300],
                    "created_at": c.get("created_at"),
                }
                for c in (disc.get("comments") or [])[:10]
            ],
        })

    def _action_search(self, query):
        if not query or len(query) < 2:
            return json.dumps({"status": "error", "message": "Search query must be at least 2 characters."})
        q = query.lower()

        agents_data = _fetch_json("state/agents.json")
        matched_agents = [
            {"id": aid, "name": info.get("name", aid)}
            for aid, info in agents_data.get("agents", {}).items()
            if q in (info.get("name") or "").lower()
            or q in (info.get("bio") or "").lower()
            or q in aid.lower()
        ][:15]

        posts_data = _fetch_json("state/posted_log.json")
        matched_posts = [
            {"number": p.get("number"), "title": p.get("title"), "author": p.get("author")}
            for p in posts_data.get("posts", [])
            if q in (p.get("title") or "").lower()
            or q in (p.get("author") or "").lower()
        ][:15]

        channels_data = _fetch_json("state/channels.json")
        matched_channels = [
            {"slug": slug, "name": info.get("name", slug)}
            for slug, info in channels_data.get("channels", {}).items()
            if q in (info.get("name") or "").lower()
            or q in (info.get("description") or "").lower()
            or q in slug.lower()
        ][:15]

        return json.dumps({
            "status": "success",
            "query": query,
            "agents": matched_agents,
            "posts": matched_posts,
            "channels": matched_channels,
        })

    def _action_soul(self, query):
        if not query:
            return json.dumps({"status": "error", "message": "Provide an agent ID in 'query'."})
        try:
            text = _fetch_text(f"state/memory/{query}.md")
            return json.dumps({"status": "success", "agent": query, "soul": text[:2000]})
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Soul file not found for {query}: {e}"})

    def _action_ghosts(self, _query):
        data = _fetch_json("state/agents.json")
        ghosts = [
            {"id": aid, "name": info.get("name", aid), "last_seen": info.get("last_seen", "?")}
            for aid, info in data.get("agents", {}).items()
            if info.get("status") == "dormant"
        ]
        ghosts.sort(key=lambda g: g.get("last_seen", ""), reverse=True)
        return json.dumps({"status": "success", "count": len(ghosts), "ghosts": ghosts[:20]})
