/** Normalize JSON returned by MediWise Python commands for action adapters. */
export function actionResult(result) {
  if (result?.status === 'error') {
    return {
      status: 'error',
      error: result.message ?? result.error ?? 'Python action returned an error',
      result,
    };
  }
  return { status: 'ok', result };
}
