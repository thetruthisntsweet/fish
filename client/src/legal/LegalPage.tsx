// The terms of use or the privacy policy, top to bottom (Terms and Privacy §1-3; T3.8), in
// the version this site shows. Anyone can read them, signed in or not.
import { withEmailLinks } from "../study/emailLinks.tsx";
import { Link } from "../screens/Link.tsx";
import type { LegalBlock, LegalDocument } from "./legal.ts";

function Blocks({ blocks }: { blocks: readonly LegalBlock[] }) {
  return blocks.map((block, i) => {
    switch (block.kind) {
      case "paragraph":
        return <p key={i}>{withEmailLinks(block.text)}</p>;
      case "list":
        return (
          <ul key={i}>
            {block.items.map((item) => (
              <li key={item}>{withEmailLinks(item)}</li>
            ))}
          </ul>
        );
      case "table":
        return (
          <div key={i} className="table-scroll">
            <table>
              <thead>
                <tr>
                  {block.header.map((cell) => (
                    <th key={cell} scope="col">
                      {cell}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {block.rows.map((row) => (
                  <tr key={row[0]}>
                    {row.map((cell, j) => (
                      <td key={j}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
    }
  });
}

export function LegalPage({ document }: { document: LegalDocument }) {
  return (
    <>
      <article className="study" aria-labelledby="legal-title">
        <h1 id="legal-title">{document.title}</h1>
        <p className="quiet">{document.effective}</p>
        <Blocks blocks={document.intro} />
        {document.sections.map((section) => (
          <section key={section.heading}>
            <h2>{section.heading}</h2>
            <Blocks blocks={section.blocks} />
          </section>
        ))}
      </article>
      <p>
        <Link to="/">Back to Fish</Link>
      </p>
    </>
  );
}
