// Every page's timestamps in the viewer's own time zone and locale. The server renders each
// as <time datetime="2026-09-23T15:51:09Z">2026-09-23 15:51 UTC</time> (the `timestamp`
// filter, server/views.py); this swaps the text for the local time and keeps the UTC text
// as the hover title. A date alone, <time datetime="2026-10-01">2026-10-01</time> (the
// `calendar_date` filter), is formatted in UTC: it parses as UTC midnight, which the
// viewer's own time zone could show as the day before. Without the script the server's
// text stays, which is still correct.

// A block, so its names stay out of the scope the page's other plain scripts share.
{
  const format = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  const formatDate = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeZone: "UTC",
  });

  for (const element of document.querySelectorAll("time[datetime]")) {
    const when = new Date(element.dateTime);
    if (Number.isNaN(when.getTime())) {
      continue;
    }
    const dateOnly = !element.dateTime.includes("T");
    element.title = element.textContent;
    element.textContent = (dateOnly ? formatDate : format).format(when);
  }
}
