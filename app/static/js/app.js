/* Job Automation Dashboard JS */

async function startWhatsApp() {
    try {
        const res = await fetch('/api/whatsapp/start', { method: 'POST' });
        const data = await res.json();
        document.getElementById('wa-status').textContent = data.status || 'starting';
        alert('WhatsApp monitor ' + (data.status || 'started'));
    } catch (e) {
        alert('Error starting WhatsApp: ' + e.message);
    }
}

async function stopWhatsApp() {
    try {
        const res = await fetch('/api/whatsapp/stop', { method: 'POST' });
        const data = await res.json();
        document.getElementById('wa-status').textContent = data.status || 'stopped';
        alert('WhatsApp monitor stopped');
    } catch (e) {
        alert('Error stopping WhatsApp: ' + e.message);
    }
}

async function processText() {
    const text = document.getElementById('test-text').value.trim();
    if (!text) {
        alert('Please enter a message to process');
        return;
    }

    const resultDiv = document.getElementById('test-result');
    resultDiv.style.display = 'block';
    resultDiv.style.background = '#e9ecef';
    resultDiv.textContent = 'Processing...';

    try {
        const res = await fetch('/api/process-text', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text, group: 'Manual Test' }),
        });
        const data = await res.json();

        resultDiv.style.background = data.status === 'ignored' ? '#f8d7da' :
                                     data.status === 'sent' || data.status === 'submitted' ? '#d4edda' :
                                     '#fff3cd';
        resultDiv.textContent = JSON.stringify(data, null, 2);

        // Reload page after a short delay to show new job
        if (data.job_id) {
            setTimeout(() => location.reload(), 2000);
        }
    } catch (e) {
        resultDiv.style.background = '#f8d7da';
        resultDiv.textContent = 'Error: ' + e.message;
    }
}

async function retryJob(jobId) {
    if (!confirm('Retry this job?')) return;
    try {
        const res = await fetch(`/api/jobs/${jobId}/retry`, { method: 'POST' });
        const data = await res.json();
        alert('Retry result: ' + (data.status || 'unknown'));
        location.reload();
    } catch (e) {
        alert('Error retrying: ' + e.message);
    }
}

async function approveJob(jobId) {
    if (!confirm('Approve and process this job?')) return;
    try {
        const res = await fetch(`/api/jobs/${jobId}/approve`, { method: 'POST' });
        const data = await res.json();
        alert('Approval result: ' + (data.status || 'unknown'));
        location.reload();
    } catch (e) {
        alert('Error approving: ' + e.message);
    }
}
