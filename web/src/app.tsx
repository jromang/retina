// Application bootstrap — everything `main.tsx` imports *after* it has settled the language.
//
// The complete workbench shell — title bar (menus, command center, zone toggles), activity bar,
// exclusive sidebar, tabbed center area (dockview), right zone, bottom zone, status bar and
// command palette. `app.layout.*` typed in the console really does drive the panels.
//
// This module is deliberately kept separate from `main.tsx`: the label tables (`commands.ts`,
// `panels.ts`, `menus.ts`) are built when their module is evaluated, that is, at import time.
// Importing them before `resolveInitialLocale()` has decided would freeze the interface in the
// fallback language, and a reload would be the only way out. See `shell/locale.ts`.

import { render } from 'preact';

import { connectDocs } from './center/docTarget';
import { connectChat } from './chat/chat';
import { connectTranscript } from './console/transcript';
import { connectNotifications } from './notifications/store';
import { connectPipeline } from './pipeline/model';
import { connectProject } from './project/project';
import { connectJobs } from './processes/jobs';
import { connectRtp } from './processes/rtp';
import { connectScripts } from './scripts/scripts';
import { connectLayout } from './shell/layoutClient';
import { connectWindow } from './shell/titlebar/windowClient';
import { Workbench } from './shell/Workbench';
import { connectStore } from './state/store';
import './styles/tokens.css';

// Order matters: the notification subscribers must be in place before `connectStore` opens the
// WebSocket, otherwise the first messages are lost.
connectLayout();
connectTranscript();
connectNotifications();
connectJobs();
connectPipeline();
connectRtp();
connectProject();
connectScripts();
connectDocs();
connectChat();
connectWindow(); // no-op outside the native shell
connectStore();

const root = document.getElementById('root');
if (root) render(<Workbench />, root);
