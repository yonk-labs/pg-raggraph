// pg-raggraph web UI logic. Lives in its own file (not inline in
// index.html) so the CSP can drop 'unsafe-inline' from script-src (PR-219).
let network = null;

async function loadStatus() {
    const resp = await fetch('/status');
    const data = await resp.json();
    document.getElementById('stats').innerHTML =
        `📊 ${data.documents} docs | ${data.entities} entities | ${data.relationships} relationships`;
}

async function loadGraph() {
    const resp = await fetch('/graph');
    const data = await resp.json();
    if (!data.nodes.length) return;

    const container = document.getElementById('graph');
    const nodes = new vis.DataSet(data.nodes.map(n => ({
        id: n.id, label: n.label, group: n.group,
        font: { color: '#e4e4e7' }
    })));
    const edges = new vis.DataSet(data.edges.map((e, i) => ({
        id: i, from: e.from, to: e.to, label: e.label,
        arrows: 'to', font: { color: '#71717a', size: 10 }
    })));

    // vis-network uses node labels for from/to matching
    const nodeMap = {};
    data.nodes.forEach(n => nodeMap[n.label] = n.id);
    const mappedEdges = new vis.DataSet(data.edges.map((e, i) => ({
        id: i, from: nodeMap[e.from], to: nodeMap[e.to],
        label: e.label, arrows: 'to',
        font: { color: '#71717a', size: 10 }, color: { color: '#4f46e5' }
    })));

    const options = {
        nodes: { shape: 'dot', size: 16, borderWidth: 2,
            color: { border: '#6366f1', background: '#312e81' } },
        edges: { width: 1, color: { color: '#4f46e5' }, smooth: { type: 'continuous' } },
        physics: { stabilization: { iterations: 100 } },
        layout: { improvedLayout: true }
    };
    network = new vis.Network(container, { nodes, edges: mappedEdges }, options);
}

async function askQuestion() {
    const input = document.getElementById('question');
    const q = input.value.trim();
    if (!q) return;
    input.value = '';

    const chat = document.getElementById('chat');
    chat.innerHTML += `<div class="msg user">${escapeHtml(q)}</div>`;

    // Show typing indicator
    const typingId = 'typing-' + Date.now();
    chat.innerHTML += `<div class="msg assistant" id="${typingId}">Thinking...</div>`;
    chat.scrollTop = chat.scrollHeight;

    const formData = new FormData();
    formData.append('question', q);
    formData.append('mode', 'smart');

    const resp = await fetch('/ask', { method: 'POST', body: formData });
    const data = await resp.json();

    let html = '';
    if (data.answer) {
        html += `<p style="white-space:pre-wrap;">${escapeHtml(data.answer)}</p>`;
    } else {
        html += '<p>No relevant information found.</p>';
    }
    if (data.chunks && data.chunks.length > 0) {
        const sources = [...new Set(data.chunks.map(c => c.source).filter(Boolean))];
        if (sources.length) {
            html += `<div class="sources">📎 ${sources.map(s => escapeHtml(s.split('/').pop())).join(', ')} · ${Math.round(data.latency_ms)}ms · ${data.query_mode}</div>`;
        }
    }
    if (data.entities && data.entities.length > 0) {
        html += `<div class="entities">${data.entities.map(e =>
            `<span>${escapeHtml(e)}</span>`).join('')}</div>`;
    }

    document.getElementById(typingId).innerHTML = html;
    chat.scrollTop = chat.scrollHeight;
}

function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
}

async function uploadFiles() {
    const input = document.getElementById('upload-files');
    const status = document.getElementById('upload-status');
    if (!input.files.length) { status.textContent = 'No files selected.'; return; }
    status.textContent = `Uploading ${input.files.length} file(s)...`;
    const form = new FormData();
    for (const f of input.files) form.append('files', f);
    try {
        const resp = await fetch('/ingest', { method: 'POST', body: form });
        const data = await resp.json();
        status.textContent = `✓ ${data.documents} docs | ${data.entities} entities`;
        input.value = '';
        loadStatus();
        loadGraph();
    } catch (e) {
        status.textContent = `Error: ${e.message}`;
    }
}

// Wired here instead of onclick= attributes: inline handlers would require
// 'unsafe-inline' in script-src.
document.getElementById('upload-btn').addEventListener('click', uploadFiles);
document.getElementById('ask-btn').addEventListener('click', askQuestion);
document.getElementById('question').addEventListener('keydown', e => {
    if (e.key === 'Enter') askQuestion();
});

loadStatus();
loadGraph();
