# Linear Issue Tracking Rules

## Overview

All development work on the Asterisk AI Voice Agent project MUST be tracked using Linear issue tracking via the Linear MCP integration.

## Mandatory Requirements

### 1. Issue Creation

**BEFORE starting any implementation work**, create a Linear issue with:

- **Clear title** using format: `[P0-P3] Brief description - Component affected`
- **Comprehensive description** including:
  - Summary of the problem
  - Impact analysis (what's broken, what works)
  - Symptoms (observable behavior)
  - Root cause analysis (if known)
  - Evidence (logs, test calls, config)
  - Proposed solution
  - Testing steps
  - Acceptance criteria
- **Priority** (P0=Urgent, P1=High, P2=Medium, P3=Low)
- **Project** assignment (e.g., "GA v4.0 Release")
- **Team** assignment ("Asterisk AI Voice Agent")

**Tool**: Use `mcp0_create_issue()` to create issues

### 2. Issue Updates During Implementation

**Update the Linear issue** at key milestones:

1. **When starting work**: Move to "In Progress" status

   ```python
   mcp0_update_issue(id="...", state="In Progress")
   ```

2. **After code commits**: Add comment with implementation details

   ```python
   mcp0_create_comment(issueId="...", body="""
   ## Implementation Complete
   - Changed X in file Y
   - Updated config Z
   - Commit: abc123
   """)
   ```

3. **During deployment**: Update with deployment status

   ```python
   mcp0_create_comment(issueId="...", body="""
   ## Deployment Status
   - Server: voiprnd.nemtclouddispatch.com
   - Status: Building...
   """)
   ```

4. **After testing**: Document test results

   ```python
   mcp0_create_comment(issueId="...", body="""
   ## Test Results
   - Call ID: 1234567890.1234
   - Result: ✅ Pass / ❌ Fail
   - Evidence: logs, metrics
   """)
   ```

5. **Upon completion**: Move to "Done" and add summary

   ```python
   mcp0_update_issue(id="...", state="Done")
   mcp0_create_comment(issueId="...", body="## ✅ Complete - Summary...")
   ```

### 3. Issue Lifecycle States

Use these states appropriately:

- **Backlog**: Issue created, not yet started
- **In Progress**: Actively working on it
- **In Review**: Code implemented, awaiting review/testing
- **Done**: Completed and verified
- **Duplicate**: Duplicate of another issue
- **Canceled**: No longer needed

### 4. Linking Related Issues

When issues are related, link them in the description:

```markdown
## Related Issues
- Blocked by: AAVA-27
- Blocks: AAVA-29
- Duplicate of: AAVA-22
```

### 5. Search Before Creating

**ALWAYS search for existing issues** before creating new ones:

```python
mcp0_list_issues(query="pipeline audio codec", limit=10)
```

Avoid creating duplicates. If similar issue exists, update it instead.

## Example Workflow

### Bug Fix Workflow

```python
# 1. Search for existing issue
issues = mcp0_list_issues(query="pipeline STT codec")

# 2. Create new issue if none exists
issue = mcp0_create_issue(
    title="[P0] Pipeline STT Codec Mismatch",
    description="...",  # Comprehensive details
    priority=1,  # P0
    team="Asterisk AI Voice Agent",
    project="GA v4.0 Release"
)

# 3. Start work
mcp0_update_issue(id=issue["id"], state="In Progress")

# 4. Implement fix
# ... write code, commit, push ...

# 5. Update with implementation
mcp0_create_comment(
    issueId=issue["id"],
    body="## Implementation Complete\n- Fixed X\n- Commit: abc123"
)

# 6. Deploy
# ... deploy to server ...

# 7. Test
# ... make test calls ...

# 8. Complete
mcp0_update_issue(id=issue["id"], state="Done")
mcp0_create_comment(
    issueId=issue["id"],
    body="## ✅ Verified\n- Test call: 123.456\n- Result: Pass"
)
```

### Feature Implementation Workflow

```python
# 1. Create feature issue
issue = mcp0_create_issue(
    title="[P2] Add validation at startup",
    description="...",
    priority=3,
    team="Asterisk AI Voice Agent"
)

# 2. Break down into subtasks (as comments)
mcp0_create_comment(
    issueId=issue["id"],
    body="""
    ## Implementation Plan
    - [ ] Task 1: Add validation function
    - [ ] Task 2: Call at startup
    - [ ] Task 3: Add tests
    - [ ] Task 4: Update docs
    """
)

# 3. Update as tasks complete
# (same as bug fix workflow)
```

## Integration with Development Workflow

### Git Commit Messages

**Include Linear issue ID** in commit messages:

```bash
git commit -m "fix(pipelines): Add audio transcoding

Fixes adapter codec mismatch by transcoding PCM16@16kHz
to configured format before sending to API.

Related: Linear AAVA-28"
```

### Deployment Notes

When deploying, **document in Linear**:

```python
mcp0_create_comment(
    issueId="...",
    body="""
    ## Deployment
    - Commit: abc123
    - Server: voiprnd.nemtclouddispatch.com
    - Time: 2025-10-28 13:30 PST
    - Status: ✅ Success
    """
)
```

### Testing Evidence

**Always document test results** in Linear:

```python
mcp0_create_comment(
    issueId="...",
    body="""
    ## Test Results
    
    ### Test Call 1
    - Call ID: 1761680468.2567
    - Duration: 25 seconds
    - Result: ✅ Pass
    - Evidence: Full transcripts generated
    
    ### Test Call 2
    - Call ID: 1761680469.2568
    - Duration: 30 seconds
    - Result: ✅ Pass
    - Evidence: Two-way conversation working
    
    ## Conclusion
    All acceptance criteria met.
    """
)
```

## Benefits

✅ **Traceability**: Every change linked to an issue  
✅ **Collaboration**: Team visibility into work  
✅ **History**: Complete audit trail  
✅ **Planning**: Clear priorities and backlog  
✅ **Metrics**: Track velocity and bottlenecks  
✅ **Documentation**: Self-documenting process

## Tools Reference

### Linear MCP Functions

- `mcp0_create_issue()` - Create new issue
- `mcp0_update_issue()` - Update issue state/fields
- `mcp0_get_issue()` - Get issue details
- `mcp0_list_issues()` - Search issues
- `mcp0_create_comment()` - Add comment to issue
- `mcp0_list_comments()` - Get issue comments

See Linear MCP documentation for full API.

## Enforcement

**This is mandatory for all development work.** Commits without linked Linear issues may be rejected during code review.

For questions or issues with Linear tracking, contact the project maintainer.

---

**Last Updated**: 2025-10-28  
**Version**: 1.0
