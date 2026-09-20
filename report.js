const form = document.querySelector('#report-form');

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
  const subject = `[Boring Browser] ${values.get('category')}: ${summary}`;
  const body = [
    `Summary: ${summary}`,
    `Type: ${values.get('category')}`,
    `Browser version: ${values.get('version').trim() || 'Not provided'}`,
    `Windows version: ${values.get('windows').trim() || 'Not provided'}`,
    '',
    steps,
  ].join('\n');
  document.querySelector('#draft').value = `To: jmill004@mtroyal.ca\nSubject: ${subject}\n\n${body}`;
  document.querySelector('#open-email').href = `mailto:jmill004@mtroyal.ca?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  document.querySelector('#email-preview').hidden = false;
  document.querySelector('#report-status').textContent = 'Draft prepared—not sent. Review it, then open your email app to send.';
  document.querySelector('#draft').focus();
});
