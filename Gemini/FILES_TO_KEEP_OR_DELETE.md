# Files to Keep or Delete After Migration

## ✅ IMPORTANT: database.py is STILL NEEDED!

**`database.py` is NOT obsolete!** It's still used for:
- ✅ Session storage (`save_session`, `load_session`)
- ✅ Session deletion (`delete_session`)
- ✅ Session listing (`list_all_sessions`)
- ✅ Database initialization (`init_db`)

**What was removed from database.py:**
- ❌ Prompts table (removed)
- ❌ `get_prompts()` function (removed)
- ❌ `update_prompts()` function (removed)

**Used by:**
- `app.py` - Lines 18, 92, 145, 157, 159, 209, 265, 303
- `demo.py` - Line 25
- `child_learning_assistant.py` - For loading sessions in API context

## 🗑️ Files That CAN Be Deleted (Obsolete)

### 1. `update_prompts_for_age_flexibility.py`
**Why:** Updates database prompts which no longer exist
**Status:** OBSOLETE - Safe to delete

### 2. `update_prompts_for_audio.py`
**Why:** Updates database prompts which no longer exist
**Status:** OBSOLETE - Safe to delete

## ⚠️ Files That Are BROKEN (Need Update or Delete)

### 1. `diagnose_validation.py`
**Issue:** Calls `database.get_prompts()` which no longer exists
**Options:**
- **Option A:** Update to use `prompts.get_prompts()` instead
- **Option B:** Delete if not needed

**Current code (broken):**
```python
prompts = database.get_prompts()  # ❌ This doesn't exist anymore
```

**Fixed code would be:**
```python
import prompts as prompts_module
prompts_dict = prompts_module.get_prompts()  # ✅ Use hardcoded prompts
```

### 2. `demo_TTS.py`
**Status:** Need to check if it uses `database.get_prompts()`

## 📋 Core Files (KEEP)

These are essential and actively used:

| File | Purpose | Status |
|------|---------|--------|
| `app.py` | Flask API server | ✅ KEEP |
| `child_learning_assistant.py` | Core assistant logic | ✅ KEEP |
| `database.py` | Session storage | ✅ KEEP |
| `demo.py` | Interactive CLI demo | ✅ KEEP |
| `prompts.py` | Hardcoded prompts | ✅ KEEP |
| `age_prompts.json` | Age-based prompts | ✅ KEEP |
| `category_prompts.json` | Category prompts | ✅ KEEP |
| `config.json` | API configuration | ✅ KEEP |

## 🧪 Test Files (Your Choice)

These test files might still be useful, but they may also reference old database prompt functions:

| File | Might Be Broken? | Recommendation |
|------|------------------|----------------|
| `test_api.py` | Maybe | Check if used, update or delete |
| `test_api_basic.py` | Maybe | Check if used, update or delete |
| `test_state_machine.py` | Maybe | Check if used, update or delete |
| `test_stuck_detection.py` | Maybe | Check if used, update or delete |

## 📚 Documentation Files (KEEP)

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Project instructions |
| `README.md` | Project overview |
| `MASTERY_SYSTEM.md` | Mastery feature docs |
| `DEDICATED_HINT_SYSTEM.md` | Hint system docs |
| `AGE_FLEXIBILITY_FIX.md` | Age prompting fix explanation |
| `CATEGORY_PROMPTS_GUIDE.md` | How to write category prompts |
| `HARDCODED_PROMPTS_MIGRATION.md` | Migration guide |
| `NEW_PROMPTING_SYSTEM_SUMMARY.md` | New prompting overview |
| `TESTING_SCENARIOS.md` | Test scenarios |
| `QUICK_START_AFTER_MIGRATION.md` | Quick start guide |

## 🎯 Recommended Actions

### Definitely Delete (Obsolete)
```bash
del update_prompts_for_age_flexibility.py
del update_prompts_for_audio.py
```

### Fix or Delete (Broken)
```bash
# Option 1: Fix diagnose_validation.py to use prompts.get_prompts()
# Option 2: Delete if not needed
del diagnose_validation.py
```

### Check and Decide (Test files)
Review these test files and decide if you want to keep/fix them:
- `test_api.py`
- `test_api_basic.py`
- `test_state_machine.py`
- `test_stuck_detection.py`
- `demo_TTS.py`

## Summary

**Keep:**
- ✅ `database.py` - Still needed for sessions!
- ✅ `prompts.py` - New hardcoded prompts
- ✅ Core files (app.py, demo.py, etc.)
- ✅ Config files (age_prompts.json, etc.)
- ✅ Documentation

**Delete:**
- ❌ `update_prompts_for_age_flexibility.py`
- ❌ `update_prompts_for_audio.py`
- ❌ `diagnose_validation.py` (if not needed)

**Your Choice:**
- ⚠️ Test files - check if you use them
