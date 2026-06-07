window.addEventListener("load", () => {
  const consoleLinks = document.querySelectorAll('a[href="/console"]');
  const isLocal = ["localhost", "127.0.0.1"].includes(window.location.hostname);

  for (const link of consoleLinks) {
    if (isLocal) continue;
    link.title = "The patient console is intended for the local demo environment.";
  }
});
