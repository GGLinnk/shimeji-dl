const fs = require('fs');
const path = require('path');

class ReleaseFailure extends Error {}

function fail(message) {
  throw new ReleaseFailure(message);
}

async function guarded(core, action) {
  try {
    await action();
  } catch (error) {
    if (error instanceof ReleaseFailure) {
      core.setFailed(error.message);
      return;
    }
    throw error;
  }
}

async function getMainSha(github, context) {
  const { owner, repo } = context.repo;
  const response = await github.rest.git.getRef({ owner, repo, ref: 'heads/main' });
  return response.data.object.sha;
}

async function assertTaggedCommitBelongsToMain(github, context, sha) {
  const { owner, repo } = context.repo;
  const response = await github.rest.repos.compareCommitsWithBasehead({
    owner,
    repo,
    basehead: `${sha}...main`,
  });
  if (!['ahead', 'identical'].includes(response.data.status)) {
    fail(`Tagged commit ${sha} is not an ancestor of main`);
  }
}

async function findQualifiedRun(github, context, sha) {
  const prefix = process.env.DIST_ARTIFACT_PREFIX;
  if (!prefix) fail('DIST_ARTIFACT_PREFIX is missing');

  const { owner, repo } = context.repo;
  const runs = await github.paginate(github.rest.actions.listWorkflowRuns, {
    owner,
    repo,
    workflow_id: 'ci.yml',
    branch: 'main',
    event: 'push',
    status: 'success',
    head_sha: sha,
    per_page: 100,
  });

  const run = runs.find(
    (candidate) =>
      candidate.head_sha === sha &&
      candidate.head_branch === 'main' &&
      candidate.event === 'push' &&
      candidate.conclusion === 'success',
  );
  if (!run) {
    fail(`No successful push/main CI run found for ${sha}`);
  }

  const artifactName = `${prefix}-${sha}`;
  const artifacts = await github.paginate(github.rest.actions.listWorkflowRunArtifacts, {
    owner,
    repo,
    run_id: run.id,
    per_page: 100,
  });
  const artifact = artifacts.find(
    (candidate) => candidate.name === artifactName && !candidate.expired,
  );
  if (!artifact) {
    fail(`CI run ${run.id} has no non-expired ${artifactName} artifact`);
  }

  return { run, artifact, artifactName };
}

async function qualify({ github, context, core }) {
  await guarded(core, async () => {
    const mode = process.env.RELEASE_MODE;
    const tag = process.env.RELEASE_TAG;
    const sha = context.sha;

    if (!mode || !tag) fail('Release mode/tag are missing');

    if (mode === 'prepare') {
      const mainSha = await getMainSha(github, context);
      if (sha !== mainSha) {
        fail(`Manual release SHA ${sha} is not current main ${mainSha}`);
      }
    } else if (mode === 'publish') {
      await assertTaggedCommitBelongsToMain(github, context, sha);
    } else {
      fail(`Unsupported release mode: ${mode}`);
    }

    const { run, artifact, artifactName } = await findQualifiedRun(github, context, sha);
    core.info(`Qualified CI run ${run.id}, artifact ${artifact.id} (${artifactName})`);
    core.setOutput('run-id', String(run.id));
    core.setOutput('artifact-name', artifactName);
  });
}

async function createTagAndDispatch({ github, context, core }) {
  await guarded(core, async () => {
    const tag = process.env.RELEASE_TAG;
    if (!tag) fail('RELEASE_TAG is missing');

    const { owner, repo } = context.repo;
    try {
      await github.rest.git.createRef({
        owner,
        repo,
        ref: `refs/tags/${tag}`,
        sha: context.sha,
      });
    } catch (error) {
      if (error.status === 422) fail(`Tag ${tag} already exists`);
      throw error;
    }
    core.info(`Created ${tag} at ${context.sha}`);

    await github.rest.actions.createWorkflowDispatch({
      owner,
      repo,
      workflow_id: 'publish.yml',
      ref: tag,
    });
    core.info(`Dispatched publish.yml on ${tag}`);
  });
}

async function findOrCreateRelease(github, context, tag) {
  const { owner, repo } = context.repo;
  try {
    const existing = await github.rest.repos.getReleaseByTag({ owner, repo, tag });
    return existing.data;
  } catch (error) {
    if (error.status !== 404) throw error;
  }

  const created = await github.rest.repos.createRelease({
    owner,
    repo,
    tag_name: tag,
    target_commitish: context.sha,
    name: tag,
    generate_release_notes: true,
    draft: false,
    prerelease: false,
  });
  return created.data;
}

async function createRelease({ github, context, core }) {
  await guarded(core, async () => {
    const tag = process.env.RELEASE_TAG;
    if (!tag) fail('RELEASE_TAG is missing');

    const files = fs
      .readdirSync('dist', { withFileTypes: true })
      .filter((entry) => entry.isFile())
      .map((entry) => path.join('dist', entry.name))
      .sort();

    if (files.length === 0) fail('No distribution files found in dist/');

    const { owner, repo } = context.repo;
    const release = await findOrCreateRelease(github, context, tag);
    const assets = await github.paginate(github.rest.repos.listReleaseAssets, {
      owner,
      repo,
      release_id: release.id,
      per_page: 100,
    });
    const existing = new Set(assets.map((asset) => asset.name));

    for (const file of files) {
      const name = path.basename(file);
      if (existing.has(name)) {
        core.info(`Release asset already exists: ${name}`);
        continue;
      }
      const data = fs.readFileSync(file);
      await github.rest.repos.uploadReleaseAsset({
        owner,
        repo,
        release_id: release.id,
        name,
        data,
        headers: {
          'content-type': 'application/octet-stream',
          'content-length': data.length,
        },
      });
      core.info(`Uploaded release asset: ${name}`);
    }
  });
}

module.exports = {
  qualify,
  createTagAndDispatch,
  createRelease,
};
