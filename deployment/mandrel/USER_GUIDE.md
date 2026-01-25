# Mandrel User Guide: Persistent AI Memory for Development

## What is Mandrel?

**Mandrel is your AI's long-term memory.** It's an MCP (Model Context Protocol) server that helps AI assistants (like me in Cursor) remember important information across sessions.

### The Problem It Solves

Without Mandrel, every conversation with an AI assistant starts from scratch. You have to:
- Re-explain your project structure
- Re-explain architectural decisions
- Re-explain what you're working on
- Re-explain past bugs and fixes

**With Mandrel, the AI remembers:**
- Your project's architecture and design decisions
- Past development context and learnings
- Task progress and milestones
- Important code patterns and solutions

## How It Works

Mandrel stores information in PostgreSQL with semantic search (vector embeddings). This means:
- **Semantic search**: Find relevant information even if you don't remember exact keywords
- **Persistent storage**: Information survives across sessions, reboots, and updates
- **Project organization**: Organize information by project
- **Context types**: Categorize information (code, decisions, errors, discussions, etc.)

## Quick Start

### 1. Connect Cursor to Mandrel

**Option A: Via Cursor Settings (Recommended)**

1. Open Cursor Settings
2. Go to MCP Servers section
3. Add Mandrel:
   ```json
   {
     "mcpServers": {
       "mandrel": {
         "url": "http://your-server:8082",
         "transport": "http"
       }
     }
   }
   ```

**Option B: Via Config File**

1. Copy the template: `cp mcps/mandrel/SERVER_METADATA.json.example mcps/mandrel/SERVER_METADATA.json`
2. Edit `mcps/mandrel/SERVER_METADATA.json` and replace `your-server` with your actual server hostname/IP

Or edit `~/.cursor/mcp.json` directly:
```json
{
  "mcpServers": {
    "mandrel": {
      "url": "http://your-server:8082",
      "transport": "http"
    }
  }
}
```

**For Antigravity/VS Code:**
1. Open Antigravity Settings → MCP Servers (or use "Manage MCP Servers" from agent panel)
2. Add Mandrel configuration:
   ```json
   {
     "mcpServers": {
       "mandrel": {
         "url": "http://your-server:8082",
         "transport": "http"
       }
     }
   }
   ```
3. **Important:** Use port `8082` (MCP HTTP Bridge), not `8081` (direct REST API)
4. Restart Antigravity to load the configuration

### 2. Test Connection

Ask me (the AI) to:
```
"Test Mandrel connection - use mandrel_ping"
```

Or check manually:
```bash
# Test bridge health
curl http://your-server:8082/health

# Test direct Mandrel API (for debugging)
curl http://your-server:8081/health
```

## Core Concepts

### Projects

Mandrel organizes everything by **projects**. Think of a project as a workspace or codebase.

**Common workflow:**
1. Create a project for your trading bot: `project_create` with name "LLM-Micro-Cap-Trading-Bot"
2. Switch to that project: `project_switch`
3. All context you store is associated with that project

### Context Types

When storing information, you categorize it:

| Type | When to Use |
|------|-------------|
| `code` | Code snippets, patterns, implementations |
| `decision` | Architectural decisions, design choices |
| `error` | Bugs, error messages, troubleshooting |
| `discussion` | Conversations, brainstorming, ideas |
| `planning` | Roadmaps, feature plans, TODO lists |
| `completion` | Finished features, completed tasks |
| `milestone` | Major achievements, version releases |
| `reflections` | Post-mortems, lessons learned |
| `handoff` | Notes for other developers/AI sessions |

### Tags

Add tags for better organization:
- `["authentication", "security"]` - For auth-related context
- `["bug-fix", "redis"]` - For Redis bug fixes
- `["feature", "dashboard"]` - For dashboard features

## Common Use Cases

### 1. Starting a New Session

**Goal**: Get up to speed on what you're working on

**Ask me:**
```
"Check Mandrel for recent context about what I'm working on"
```

**What I'll do:**
1. Call `mandrel_ping` to verify connection
2. Call `project_current` to see active project
3. Call `context_get_recent` to see recent context
4. Call `task_list` to see active tasks

### 2. Storing Important Information

**Scenario**: You just fixed a tricky Redis connection bug

**Ask me:**
```
"Store this in Mandrel: Fixed Redis connection issue by patching queueManager.ts to read from REDIS_URL environment variable instead of hardcoded localhost. The patch is in deployment/mandrel/patches/apply-redis-patch.py"
```

**What I'll do:**
1. Call `context_store` with:
   - `content`: Your description
   - `type`: "error" (or "completion" if it's fixed)
   - `tags`: ["redis", "bug-fix", "docker"]

**Later, when you ask:**
```
"How did we fix the Redis connection issue?"
```

I'll call `context_search` with query "Redis connection fix" and find your stored context.

### 3. Recording Architectural Decisions

**Scenario**: You decide to use PostgreSQL with pgvector for semantic search

**Ask me:**
```
"Record this decision in Mandrel: We're using PostgreSQL with pgvector extension for semantic search instead of a separate vector database. Rationale: Simpler infrastructure, already have PostgreSQL, pgvector is mature and performant."
```

**What I'll do:**
1. Call `decision_record` with:
   - `title`: "Use PostgreSQL + pgvector for semantic search"
   - `description`: Your full description
   - `rationale`: Why this decision was made
   - `decisionType`: "architecture"
   - `impactLevel`: "high"

**Later, when you ask:**
```
"Why did we choose pgvector?"
```

I'll call `decision_search` to find this decision.

### 4. Tracking Tasks

**Scenario**: You want to track a feature you're building

**Ask me:**
```
"Create a task in Mandrel: Implement Redis patch for Mandrel build process"
```

**What I'll do:**
1. Call `task_create` with:
   - `title`: "Implement Redis patch for Mandrel build process"
   - `description`: Details (if provided)
   - `status`: "in_progress"

**Later, when you ask:**
```
"What tasks am I working on?"
```

I'll call `task_list` to show active tasks.

### 5. Finding Past Information

**Scenario**: You remember discussing something about Docker networking but can't find it

**Ask me:**
```
"Search Mandrel for information about Docker networking configuration"
```

**What I'll do:**
1. Call `smart_search` with query "Docker networking configuration"
2. This searches across contexts, decisions, and tasks
3. Returns semantically similar results even if exact keywords don't match

## Practical Examples

### Example 1: Onboarding a New AI Session

**You:**
```
"Help me get started - check what I've been working on"
```

**I'll:**
1. Ping Mandrel to verify connection
2. Check current project
3. Get recent context (last 10 items)
4. List active tasks
5. Summarize what you're working on

### Example 2: Storing a Learning

**You:**
```
"Remember this: When building Docker images with native modules on Alpine, use node:22-slim (Debian) instead of node:22-alpine. Alpine's musl libc causes issues with onnxruntime-node and sharp."
```

**I'll:**
1. Store this as `context_store` with:
   - `type`: "code"
   - `tags`: ["docker", "alpine", "native-modules", "troubleshooting"]

**Later:**
```
"What issues did we have with Alpine Docker images?"
```

I'll find this stored context.

### Example 3: Recording a Bug Fix

**You:**
```
"Record this bug fix: Fixed Mandrel Redis connection by creating build-time patch. The issue was hardcoded localhost in queueManager.ts. Solution: Python patch script that runs during Docker build to replace hardcoded values with REDIS_URL parsing."
```

**I'll:**
1. Store as `context_store` with:
   - `type`: "completion"
   - `tags`: ["mandrel", "redis", "docker", "bug-fix", "patch"]

**Later:**
```
"How did we fix the Mandrel Redis issue?"
```

I'll find this fix.

### Example 4: Planning a Feature

**You:**
```
"Store this plan: Add support for multiple Redis instances. Need to update docker-compose.yml to allow configuring multiple Redis URLs. Will require changes to queueManager.ts to support connection pooling."
```

**I'll:**
1. Store as `context_store` with:
   - `type`: "planning"
   - `tags`: ["redis", "feature", "docker-compose"]

**Later:**
```
"What features are we planning for Redis?"
```

I'll find this plan.

## Available Tools Reference

### System Tools
- **`mandrel_ping`** - Test if Mandrel is reachable
- **`mandrel_status`** - Get server health and status
- **`mandrel_help`** - List all available tools by category
- **`mandrel_explain`** - Get detailed help for a specific tool
- **`mandrel_examples`** - Get usage examples for a tool

### Context Management
- **`context_store`** - Store development context
  - Required: `content` (string), `type` (string)
  - Optional: `tags` (array of strings)
- **`context_search`** - Search stored contexts semantically
  - Required: `query` (string)
  - Optional: `type`, `tags`, `limit`
- **`context_get_recent`** - Get recent contexts (last N items)
- **`context_stats`** - Get statistics about stored contexts

### Decision Tracking
- **`decision_record`** - Record an architectural decision
  - Required: `title`, `description`, `rationale`, `decisionType`, `impactLevel`
- **`decision_search`** - Search past decisions
- **`decision_update`** - Update a decision (add notes, change status)
- **`decision_stats`** - Get statistics about decisions

### Project Management
- **`project_list`** - List all projects
- **`project_create`** - Create a new project
- **`project_switch`** - Switch to a different project
- **`project_current`** - Get current project info

### Task Management
- **`task_create`** - Create a task
  - Required: `title` (string)
  - Optional: `description`, `status`, `priority`
- **`task_list`** - List tasks (optional: filter by status)
- **`task_update`** - Update task status/progress
- **`task_details`** - Get full details of a specific task

### Search
- **`smart_search`** - Cross-system semantic search (searches contexts, decisions, tasks)
- **`get_recommendations`** - Get AI recommendations based on current context

## Best Practices

### 1. Store Context Proactively

**Don't wait** for me to ask - if something is important, tell me to store it:
```
"Store this in Mandrel: [important information]"
```

### 2. Use Descriptive Tags

Good tags make information easier to find:
- ✅ `["redis", "docker", "bug-fix"]`
- ❌ `["stuff", "thing"]`

### 3. Record Decisions Immediately

When you make an architectural decision, record it right away:
```
"Record this decision: [decision details]"
```

### 4. Use Milestones

At the end of a session or after completing a feature:
```
"Store a milestone: Completed Mandrel deployment with Redis patch. All containers running and healthy."
```

### 5. Search Before Asking

If you think we've discussed something before:
```
"Search Mandrel for [topic]"
```

I'll search before giving you a generic answer.

## Troubleshooting

### "Mandrel connection failed"

**Check:**
1. Is the container running?
   ```bash
   ssh -i /path/to/your/id_rsa user@your-server "docker ps | grep mandrel"
   ```

2. Is the health endpoint responding?
   ```bash
   curl http://your-server:8081/health
   ```

3. Is Cursor configured correctly?
   - Check `mcps/mandrel/SERVER_METADATA.json` or Cursor settings

### "No results found"

**Possible reasons:**
1. No context stored yet - start storing information!
2. Query too specific - try broader search terms
3. Wrong project - check `project_current` and switch if needed

### "Tool not found"

**Check:**
1. Is Mandrel updated? New tools may have been added
2. Check available tools:
   ```bash
   curl http://your-server:8081/mcp/tools/schemas
   ```

## Advanced Usage

### Semantic Search Power

Mandrel uses vector embeddings, so searches are **semantic**, not keyword-based:

**Example:**
- You stored: "Fixed Redis connection by reading from environment variable"
- You search: "How did we configure Redis?"
- ✅ **Finds it** - even though keywords don't match exactly!

### Project Organization

Use projects to separate different codebases or workstreams:

```
project_create: "LLM-Trading-Bot"      # Main project
project_create: "Mandrel-Deployment"   # Deployment work
project_create: "Research"             # Research notes
```

Switch between projects as needed:
```
project_switch: "Mandrel-Deployment"
```

### Context Types Strategy

**Use different types strategically:**
- `code` - For reusable code patterns
- `decision` - For important architectural choices
- `error` - For bugs and troubleshooting
- `milestone` - For major achievements
- `planning` - For future work

This helps with filtering and organization.

## Getting Help

### In Cursor

Just ask me:
```
"What Mandrel tools are available?"
"How do I store context in Mandrel?"
"Show me examples of using Mandrel"
```

I can call `mandrel_help`, `mandrel_explain`, and `mandrel_examples` to help you.

### Manual API Access

You can also query Mandrel directly:

```bash
# List all tools
curl http://your-server:8081/mcp/tools/schemas

# Health check
curl http://your-server:8081/health

# Server status
curl http://your-server:8081/mcp/tools/call \
  -H "Content-Type: application/json" \
  -d '{"tool": "mandrel_status"}'
```

## Summary

**Mandrel = Your AI's Memory**

- **Store** important information as you work
- **Search** for past context when needed
- **Track** decisions, tasks, and milestones
- **Organize** by projects and tags

**The more you use it, the smarter I become!** 🧠

Start by asking me to check what's already stored, then begin storing new context as you work. Over time, Mandrel becomes an invaluable knowledge base for your project.
