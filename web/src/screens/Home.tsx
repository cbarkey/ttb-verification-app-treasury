interface Props {
  onSingle: () => void;
  onBatch: () => void;
}

export function Home({ onSingle, onBatch }: Props) {
  return (
    <div className="max-w-2xl mx-auto w-full px-6 py-16">
      <h1 className="text-2xl font-semibold tracking-tight text-center">
        What would you like to check?
      </h1>
      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        <button
          onClick={onSingle}
          className="rounded-2xl border border-zinc-200 bg-white p-8 text-left shadow-sm hover:border-sky-400 hover:shadow"
        >
          <p className="text-lg font-semibold">Check one label</p>
          <p className="mt-1 text-zinc-600">
            Type the application values, drop the image(s), get a result in a few
            seconds.
          </p>
        </button>
        <button
          onClick={onBatch}
          className="rounded-2xl border border-zinc-200 bg-white p-8 text-left shadow-sm hover:border-sky-400 hover:shadow"
        >
          <p className="text-lg font-semibold">Upload a batch</p>
          <p className="mt-1 text-zinc-600">
            One ZIP with a <span className="font-mono text-sm">manifest.csv</span> and
            the images. Results stream in; work the exceptions.
          </p>
        </button>
      </div>
    </div>
  );
}
