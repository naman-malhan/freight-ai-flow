const assert = require('assert');
const { classifyError, MESSAGES } = require('./build_error_message');

assert.strictEqual(
  classifyError({
    failedNode: 'Handle Audio via FastAPI (STT)',
    statusCode: 401,
    message: 'Unauthorized',
    bodyText: 'media_download_unauthorized_token_expired',
  }).error_code,
  'token_expired'
);

assert.strictEqual(
  classifyError({
    failedNode: 'Extract Trip Intent',
    statusCode: 504,
    message: 'timeout',
    bodyText: '',
  }).error_code,
  'api_timeout'
);

assert.strictEqual(
  classifyError({
    failedNode: 'Resolve Open Draft (CREATE)',
    statusCode: 404,
    message: 'Not Found',
    bodyText: 'no open draft',
  }).error_code,
  'draft_not_found'
);

assert.strictEqual(
  classifyError({
    failedNode: 'POST Trip Draft',
    statusCode: 500,
    message: 'Internal',
    bodyText: 'boom',
  }).error_code,
  'generic'
);

assert.strictEqual(
  classifyError({
    failedNode: 'Send Confirmation Buttons',
    statusCode: 401,
    message: 'Session has expired',
    bodyText: '',
  }).error_code,
  'token_expired'
);

assert.strictEqual(MESSAGES.stt_failed, 'Could not understand the voice note. Please type the trip details.');
assert.strictEqual(MESSAGES.stt_token, 'Voice processing unavailable right now. Please type the trip details.');

console.log('build_error_message.test.js: OK');
