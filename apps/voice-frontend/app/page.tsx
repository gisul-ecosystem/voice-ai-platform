import Link from "next/link";

import { products } from "@/lib/products";

export default function Home() {
  return (
    <main className="home-page">
      <header className="home-header">
        <p className="eyebrow">Internal demo workspace</p>
        <h1>Voice AI Platform</h1>
        <p>
          Choose a product to test the reusable real-time voice experience.
          Provider credentials and worker routing stay on the server.
        </p>
      </header>

      <div className="product-grid">
        {Object.values(products).map((product) => (
          <article className="product-card" key={product.id}>
            <p className="product-label">{product.eyebrow}</p>
            <h2>{product.title}</h2>
            <p>{product.description}</p>
            <Link className="button primary" href={product.href}>
              Open demo
            </Link>
          </article>
        ))}
      </div>

      <footer className="home-footer">
        Built for product-level integration through one session API.
      </footer>
    </main>
  );
}
