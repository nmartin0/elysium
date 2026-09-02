// setupTests.js -- runs once before every test file. Adds jest-dom's
// own matchers (toBeInTheDocument, etc.) to Vitest's expect(), the
// standard pairing confirmed directly against current (2026) docs
// before adopting it, not assumed from memory.
import '@testing-library/jest-dom'
