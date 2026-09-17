// Shared framer-motion presets (Phase 1). Deliberately restrained -- ease-out
// only, no spring/bounce -- per the "polished but don't overdo it" direction.
// Motion is applied at chart mount, card-grid entrance, and progress-bar
// stage transitions; there is no global page-transition wrapper (see the
// build plan's Phase 1 notes for why).
import type { Transition, Variants } from "framer-motion";

export const EASE_OUT: Transition["ease"] = [0.16, 1, 0.3, 1];

export const fadeInUp: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.25, ease: EASE_OUT } },
};

export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.2, ease: EASE_OUT } },
};

export const staggerChildren: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.06 } },
};
