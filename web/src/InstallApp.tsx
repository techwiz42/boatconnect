import { useEffect, useState } from "react";

interface InstallPrompt extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

const standalone = () => window.matchMedia("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true;
const onIPhone = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

/** Putting boatconnect on the phone's home screen. Android and desktop Chrome offer a real install button; iPhones have none, so they are told where to tap. Nothing shows once it is installed. */
export function InstallApp() {
  const [prompt, setPrompt] = useState<InstallPrompt | null>(null);
  const [installed, setInstalled] = useState(standalone());

  useEffect(() => {
    const ready = (e: Event) => {
      e.preventDefault(); // keep the browser's own banner away; the button below does it
      setPrompt(e as InstallPrompt);
    };
    const done = () => setInstalled(true);
    window.addEventListener("beforeinstallprompt", ready);
    window.addEventListener("appinstalled", done);
    return () => {
      window.removeEventListener("beforeinstallprompt", ready);
      window.removeEventListener("appinstalled", done);
    };
  }, []);

  if (installed) return null;
  if (!prompt && !onIPhone()) return null; // nothing to offer: a browser that cannot install it

  async function install() {
    if (!prompt) return;
    await prompt.prompt();
    if ((await prompt.userChoice).outcome === "accepted") setInstalled(true);
    setPrompt(null);
  }

  return (
    <section className="card narrow">
      <h2>Get the app</h2>
      {prompt ? (
        <>
          <p className="hint">Put boatconnect on your home screen: it opens full screen, like an app.</p>
          <button type="button" className="button" onClick={() => void install()}>
            Install boatconnect
          </button>
        </>
      ) : (
        <p>
          On an iPhone or iPad: tap the <strong>Share</strong> button in Safari, then <strong>Add to Home Screen</strong>. boatconnect then opens full screen, like an app.
        </p>
      )}
    </section>
  );
}
