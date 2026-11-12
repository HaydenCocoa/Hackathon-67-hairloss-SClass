// Chooses where the Lecturer page gets its data.
//
// The real backend is used by default. To try the page with built-in demo data instead (for example
// before the backend can recommend time slots), create frontend/.env.local with
//   VITE_LECTURER_DEMO=true
// and restart `npm run dev`.

import * as demoApi from './demoData.js'
import * as realApi from './lecturerApi.js'

export const DEMO = import.meta.env?.VITE_LECTURER_DEMO === 'true'
export const api = DEMO ? demoApi : realApi
