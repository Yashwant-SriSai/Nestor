# app.py
# The Streamlit UI. Streamlit re-runs this whole file on every click, so
# anything we want to REMEMBER (the loaded repo, finished overviews) is kept
# in st.session_state.

import streamlit as st

import json

import streamlit.components.v1 as components

import api_client

def render_mermaid(code: str) -> None:
    # Streamlit can't draw Mermaid itself, so we embed a small web page that
    # loads the Mermaid library (needs internet in YOUR browser) and draws it.
    # json.dumps safely turns the code into a JavaScript string. Replacing "</"
    # stops the diagram text from closing our <script> tag early (the code comes
    # from an LLM that read untrusted repo files). securityLevel "strict" turns
    # off clickable links and scripts inside diagrams.
    safe_code = json.dumps(code).replace("</", "<\\/")
    components.html(f"""
    <div id="out" style="font-family: sans-serif">Drawing the diagram...</div>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
    <script>
      mermaid.initialize({{ startOnLoad: false, securityLevel: "strict" }});
      mermaid.render("diagram", {safe_code})
        .then(r => {{ document.getElementById("out").innerHTML = r.svg; }})
        .catch(() => {{ document.getElementById("out").textContent =
            "Could not draw this diagram. The Mermaid code is shown below it."; }});
    </script>
    """, height=550, scrolling=True)

def go_to_step(delta: int, total: int) -> None:
    # Used as a button callback. Callbacks run BEFORE the page redraws, so the
    # new step number is already correct when the page is drawn again.
    current = st.session_state.get("step", 0)
    st.session_state["step"] = max(0, min(total - 1, current + delta))

def go_to_file(delta: int, total: int) -> None:
    # Button callback for the "Rebuild it" stepper (same idea as go_to_step).
    current = st.session_state.get("rebuild_idx", 0)
    st.session_state["rebuild_idx"] = max(0, min(total - 1, current + delta))


# Used to colour the code block in "Rebuild it".
CODE_LANGUAGES = {"py": "python", "js": "javascript", "jsx": "javascript", "json": "json",
                  "md": "markdown", "yml": "yaml", "yaml": "yaml", "toml": "toml",
                  "html": "html", "css": "css", "sh": "bash"}

st.set_page_config(page_title="Nestor", page_icon="🧭", layout="wide")

st.sidebar.title("🧭 Nestor")
# Beginner / intermediate toggle: changes how the LLM words its explanation.
level = st.sidebar.radio("Explanation level", ["beginner", "intermediate"])

st.title("Nestor")
st.caption("Paste a public GitHub repo and understand it without being scared of it.")

url = st.text_input("Public GitHub repo URL", placeholder="https://github.com/owner/repo")

if st.button("Analyze repo", type="primary"):
    # A new repo means all old results are stale, so forget them.
    st.session_state.pop("repo", None)
    st.session_state["overviews"] = {}
    st.session_state["messages"] = [] 
    try:
        with st.spinner("Cloning and reading the repo..."):
            st.session_state["repo"] = api_client.analyze(url)
    except api_client.ApiError as exc:
        st.error(str(exc))

repo = st.session_state.get("repo")
if not repo:
    st.info("Enter a repo URL above and click Analyze.")
    st.stop()  # nothing more to draw until a repo is loaded

stats = repo["stats"]
st.success(f"Loaded {repo['url']}: {stats['files_kept']} files read "
           f"({stats['files_skipped']} junk files skipped), {stats['size_mb']} MB.")
if stats["file_limit_hit"]:
    st.warning("This repo has more files than our limit, so only the most important ones were read.")

if stats["chunk_limit_hit"]:
    st.warning("The repo is large, so only the first part of the code was indexed for chat search.")

(overview_tab, tree_tab, diagrams_tab, summaries_tab,
 chat_tab, build_tab, rebuild_tab) = st.tabs(
    ["Overview", "Folder tree", "Diagrams", "File summaries", "Chat", "Run it", "Rebuild it"])

with overview_tab:
    # Cached per (repo, level): switching the toggle back doesn't call Gemini again.
    cache = st.session_state.setdefault("overviews", {})
    key = (repo["repo_id"], level)
    if key not in cache:
        try:
            with st.spinner("Gemini is reading the key files..."):
                cache[key] = api_client.overview(repo["repo_id"], level)
        except api_client.ApiError as exc:
            st.error(str(exc))

    ov = cache.get(key)
    if ov:
        st.header(ov["name"])
        st.subheader("The problem it solves")
        st.write(ov["problem"])
        st.subheader("In plain English")
        st.write(ov["summary"])

        if ov["tech_stack"]:
            st.subheader("Tech stack")
            for item in ov["tech_stack"]:
                st.markdown(f"- **{item.get('name', '?')}**: {item.get('role', '')}")

        if ov["pipeline"]:
            st.subheader("How it works, step by step")
            for number, step in enumerate(ov["pipeline"], start=1):
                st.markdown(f"{number}. {step}")

        if ov["entry_points"]:
            st.subheader("Where to start reading")
            for item in ov["entry_points"]:
                st.markdown(f"- `{item['path']}`: {item.get('why', '')}")

        if ov["key_files"]:
            st.subheader("Key files")
            for item in ov["key_files"]:
                st.markdown(f"- `{item['path']}`: {item.get('purpose', '')}")

        if ov["notes"]:
            st.caption(f"Notes: {ov['notes']}")

with tree_tab:
    st.code(repo["tree"], language="text")

with diagrams_tab:
    # Cached per (repo, kind), so each diagram is generated only once.
    cache = st.session_state.setdefault("diagrams", {})
    for kind, title in (("architecture", "Architecture"), ("dataflow", "Data flow")):
        st.subheader(title)
        key = (repo["repo_id"], kind)
        if st.button(f"Generate {title.lower()} diagram", key=f"diagram_{kind}"):
            try:
                with st.spinner("Gemini is drawing..."):
                    cache[key] = api_client.diagram(repo["repo_id"], kind)
            except api_client.ApiError as exc:
                st.error(str(exc))
        if key in cache:
            render_mermaid(cache[key])
            with st.expander("Mermaid code"):  # shown in case the drawing fails
                st.code(cache[key], language="text")

with summaries_tab:
    cache = st.session_state.setdefault("summaries", {})
    key = (repo["repo_id"], level)
    st.caption("Summarising every file can take a minute on bigger repos.")
    if st.button("Summarize every file"):
        try:
            with st.spinner("Gemini is reading every file..."):
                cache[key] = api_client.summaries(repo["repo_id"], level)
        except api_client.ApiError as exc:
            st.error(str(exc))
    if key in cache:
        for path, text in cache[key].items():
            st.markdown(f"**`{path}`**: {text}")
with chat_tab:
    # Chat history lives in st.session_state (no database), as planned.
    messages = st.session_state.setdefault("messages", [])

    for m in messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("steps"):
                # Shows what the agent searched and read to produce the answer.
                with st.expander("What the agent did"):
                    for step in m["steps"]:
                        st.markdown(f"- `{step}`")
                        
    question = st.chat_input("Ask anything about this repo")
    if question:
        history = [{"role": m["role"], "content": m["content"]} for m in messages]
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            try:
                with st.spinner("Searching the code..."):
                    result = api_client.chat(repo["repo_id"], level, question, history)
                st.markdown(result["answer"])
                # Both messages are stored only after success, so a failed call
                # doesn't leave a question without an answer in the history.
                messages.append({"role": "user", "content": question})
                messages.append({"role": "assistant", "content": result["answer"],
                                 "steps": result["steps"]})
            except api_client.ApiError as exc:
                st.error(str(exc))
with build_tab:
    # Build-mode safety: commands are only SHOWN. This app never runs anything.
    # The OS is asked first because commands differ between Windows, macOS and Linux.
    os_name = st.selectbox("Your operating system", ["windows", "macos", "linux"],
                           index=None, placeholder="Choose your OS first")
    if not os_name:
        st.info("Choose your operating system so the commands match your computer.")
    else:
        plans = st.session_state.setdefault("plans", {})
        plan_key = (repo["repo_id"], os_name, level)

        if st.button("Generate step-by-step guide"):
            try:
                with st.spinner("Gemini is writing your guide..."):
                    plans[plan_key] = api_client.build_plan(repo["repo_id"], level, os_name)
                st.session_state["step"] = 0  # a new guide starts at step 1
            except api_client.ApiError as exc:
                st.error(str(exc))

        plan = plans.get(plan_key)
        if plan:
            steps = plan["steps"]
            total = len(steps)
            idx = min(st.session_state.get("step", 0), total - 1)
            step = steps[idx]

            st.progress((idx + 1) / total)
            st.subheader(f"Step {idx + 1} of {total}: {step['title']}")
            st.write(step["explanation"])

            for command in step["commands"]:
                if command["warning"]:  # flagged by code in planner.py, not by the LLM
                    st.warning(f"⚠️ Risky command: {command['warning']}")
                st.code(command["cmd"], language="powershell" if os_name == "windows" else "bash")

            if step["expected"]:
                st.markdown(f"**You should see:** {step['expected']}")
            if step["notes"]:
                st.caption(f"Tip: {step['notes']}")
            st.caption("These commands are for YOU to run. This app never runs anything for you.")

            prev_col, next_col = st.columns(2)
            prev_col.button("← Previous", key="prev_step", on_click=go_to_step,
                            args=(-1, total), disabled=idx == 0)
            next_col.button("Next →", key="next_step", on_click=go_to_step,
                            args=(1, total), disabled=idx == total - 1)

            # Doubts are answered in the context of the CURRENT step.
            st.divider()
            st.subheader("Stuck? Ask about this step")
            doubts = st.session_state.setdefault("doubts", {})
            doubt_key = (plan_key, idx)

            with st.form(f"doubt_form_{idx}", clear_on_submit=True):
                question = st.text_input("Your question")
                error_text = st.text_area("Or paste your error / terminal output here")
                submitted = st.form_submit_button("Ask")

            if submitted:
                try:
                    with st.spinner("Thinking..."):
                        answer = api_client.build_ask(repo["repo_id"], level, os_name,
                                                      step, question, error_text)
                    doubts.setdefault(doubt_key, []).append(
                        (question or "(pasted an error)", answer))
                except api_client.ApiError as exc:
                    st.error(str(exc))

            for asked, answered in doubts.get(doubt_key, []):
                with st.chat_message("user"):
                    st.markdown(asked)
                with st.chat_message("assistant"):
                    st.markdown(answered)

with rebuild_tab:
    st.caption("Recreate the project from an empty folder, one file at a time. Files that "
               "don't depend on others come first, so nothing you create is missing a piece.")
    orders = st.session_state.setdefault("rebuild_orders", {})

    if st.button("Work out the build order"):
        try:
            with st.spinner("Reading the imports of every file..."):
                orders[repo["repo_id"]] = api_client.rebuild_plan(repo["repo_id"], level)
            st.session_state["rebuild_idx"] = 0
        except api_client.ApiError as exc:
            st.error(str(exc))

    order = orders.get(repo["repo_id"])
    if order:
        total = len(order)
        idx = min(st.session_state.get("rebuild_idx", 0), total - 1)
        entry = order[idx]

        st.progress((idx + 1) / total)
        st.subheader(f"File {idx + 1} of {total}: {entry['path']}")

        if entry["depends_on"]:
            st.markdown("**Create these first** (this file imports them): "
                        + ", ".join(f"`{dep}`" for dep in entry["depends_on"]))
        else:
            st.markdown("This file doesn't import any other file of the project, "
                        "so it is safe to create right now.")

        # One Gemini call per file the first time you open it (cached afterwards).
        # Running "Summarize every file" first fills the same cache and saves calls.
        step_cache = st.session_state.setdefault("rebuild_steps", {})
        step_key = (repo["repo_id"], level, entry["path"])
        if step_key not in step_cache:
            try:
                with st.spinner("Gemini is explaining this file..."):
                    step_cache[step_key] = api_client.rebuild_step(repo["repo_id"], level, entry["path"])
            except api_client.ApiError as exc:
                st.error(str(exc))

        step = step_cache.get(step_key)
        if step:
            st.write(step["explanation"])
            st.caption("Create this file in your empty folder, then paste this code into it:")
            extension = entry["path"].rsplit(".", 1)[-1].lower()
            st.code(step["code"], language=CODE_LANGUAGES.get(extension))

        back_col, forward_col = st.columns(2)
        back_col.button("← Previous file", key="prev_file", on_click=go_to_file,
                        args=(-1, total), disabled=idx == 0)
        forward_col.button("Next file →", key="next_file", on_click=go_to_file,
                           args=(1, total), disabled=idx == total - 1)