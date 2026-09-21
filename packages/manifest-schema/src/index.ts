/**
 * @capsule/manifest-schema
 * Shared manifest schema and pure validation engine.
 */
export * from './types.js';
export * from './validator.js';
export * from './parser.js';

import schemaJson from '../schema/capsule.manifest.schema.json' with { type: 'json' };
export { schemaJson as capsuleManifestSchema };
