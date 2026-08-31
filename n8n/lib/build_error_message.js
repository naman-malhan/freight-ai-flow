'use strict';

const MESSAGES = {
  token_expired: 'WhatsApp access expired. Please try again later.',
  stt_failed: 'Could not understand the voice note. Please type the trip details.',
  stt_token: 'Voice processing unavailable right now. Please type the trip details.',
  api_timeout: 'Service temporarily unavailable. Please retry in a moment.',
  draft_not_found: 'No open draft found. Please send trip details first.',
  generic: 'Something went wrong. Please type the trip details and try again.',
};

function classifyError({ failedNode, statusCode, message, bodyText }) {
  const node = String(failedNode || '');
  const msg = `${message || ''} ${bodyText || ''}`.toLowerCase();
  const code = Number(statusCode) || null;

  const looksToken =
    code === 401 ||
    code === 403 ||
    msg.includes('session has expired') ||
    msg.includes('oauth') ||
    msg.includes('media_download_unauthorized') ||
    msg.includes('token_expired') ||
    msg.includes('unauthorized');

  const looksTimeout =
    code === 502 ||
    code === 503 ||
    code === 504 ||
    msg.includes('timeout') ||
    msg.includes('econnrefused') ||
    msg.includes('enotfound') ||
    msg.includes('socket hang up');

  const looksDraftMissing =
    node.startsWith('Resolve Open Draft') &&
    (code === 404 || msg.includes('no open draft') || msg.includes('not found'));

  let error_code = 'generic';
  if (looksToken) error_code = 'token_expired';
  else if (looksDraftMissing) error_code = 'draft_not_found';
  else if (looksTimeout) error_code = 'api_timeout';

  // Soft-STT helpers (used by Send STT Failed path, not HTTP throw)
  if (node === '__soft_stt__') {
    if (msg.includes('media_download_unauthorized') || msg.includes('token_expired')) {
      error_code = 'stt_token';
    } else {
      error_code = 'stt_failed';
    }
  }

  return { error_code, text_body: MESSAGES[error_code] || MESSAGES.generic };
}

module.exports = { classifyError, MESSAGES };
