import type { InferenceOpts } from "../lib/bridge";
import { TUNING } from "../lib/specs";
import Modal from "./Modal";
import TuneGrid from "./TuneGrid";
import styles from "./MoreSettings.module.css";

interface Props {
  opts: InferenceOpts;
  onPatch: (patch: Partial<InferenceOpts>) => void;
  onClose: () => void;
}

// The less-used knobs: timing, pitch tracking range, index search, gain, and
// WASAPI device options. Everything here is a field described in the shared
// option spec, so adding one is a one-line change.
export default function MoreSettings({ opts, onPatch, onClose }: Props) {
  return (
    <Modal title="More settings" onClose={onClose}>
      <div className={styles.more}>
        {TUNING.map((section) => (
          <TuneGrid key={section.title} section={section} opts={opts} onPatch={onPatch} />
        ))}
      </div>
    </Modal>
  );
}
