// One "Test build" comment per pull request, updated on every build (actions/github-script).
// Success: links to the installer and the portable zip of the PR's head commit.
// Failure: a warning on top – the links below (if any) are from an earlier commit.
const MARKER = '<!-- installer-build -->';
const STALE = '<!-- stale -->';

module.exports = async ({ github, context, ok, setupUrl, setupName, portableUrl }) => {
  const pr = context.payload.pull_request;
  const sha = pr.head.sha.slice(0, 7);
  const log = `${context.serverUrl}/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId}`;

  const comments = await github.paginate(github.rest.issues.listComments, {
    ...context.repo,
    issue_number: pr.number,
    per_page: 100,
  });
  const old = comments.find((c) => c.body && c.body.includes(MARKER));

  let body;
  if (ok) {
    body = [
      MARKER,
      '### Test build',
      '',
      `Installer for \`${sha}\`: **[${setupName}](${setupUrl})**`,
      `Portable, no install: [StationJoints-win64.zip](${portableUrl}) · [build log](${log})`,
      '',
      'Downloading needs a GitHub sign-in; the links expire in 30 days. ' +
        'The setup installs over the current version, no admin rights needed.',
    ].join('\n');
  } else {
    // keep the last good links, but say plainly that they are not for this commit
    const previous = old ? old.body.split(STALE).pop().replace(MARKER, '').trim() : '';
    body = [
      MARKER,
      `> [!WARNING]`,
      `> The build for \`${sha}\` failed – [build log](${log}).` +
        (previous ? ' The links below are from an earlier commit.' : ''),
      STALE,
      previous,
    ].join('\n');
  }

  if (old) {
    await github.rest.issues.updateComment({ ...context.repo, comment_id: old.id, body });
  } else {
    await github.rest.issues.createComment({ ...context.repo, issue_number: pr.number, body });
  }
};
