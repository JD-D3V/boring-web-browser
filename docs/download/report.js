const form = document.querySelector('#report-form');
const REPO = 'https://github.com/JD-D3V/boring-web-browser';

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const values = new FormData(form);
  const summary = values.get('summary').trim();
  const steps = values.get('steps').trim();
  if (!summary || !steps) {
    const field = document.querySelector(!summary ? '#summary' : '#steps');
    field.setCustomValidity('Please enter a description, not just spaces.');
    field.reportValidity();
    field.addEventListener('input', () => field.setCustomValidity(''), { once: true });
    return;
  }
  const category = values.get('category');
  const privateReport = category === 'Security problem';
  const title = `[Boring Browser] ${category}: ${summary}`;
  const body = [
    `Summary: ${summary}`,
    `Type: ${category}`,
    `Browser version: ${values.get('version').trim() || 'Not provided'}`,
    `Windows version: ${values.get('windows').trim() || 'Not provided'}`,
    '',
    steps,
  ].join('\n');
  document.querySelector('#draft').value = `Title: ${title}\n\n${body}`;
  // GitHub fills in a new issue from these two parameters. Its private
  // security form takes no prefill, so that one is copy and paste.
  document.querySelector('#open-issue').href = privateReport
    ? `${REPO}/security/advisories/new`
    : `${REPO}/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`;
  document.querySelector('#issue-preview').hidden = false;
  document.querySelector('#report-status').textContent = privateReport
    ? 'Draft prepared, not sent. Copy it into GitHub’s private security form; only JD can read it there.'
    : 'Draft prepared, not sent. Review it, then open GitHub to post it as a public issue.';
  document.querySelector('#draft').focus();
});
