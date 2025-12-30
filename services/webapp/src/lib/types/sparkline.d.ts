// Type declaration for @fnando/sparkline
declare module '@fnando/sparkline' {
	interface SparklineOptions {
		strokeWidth?: number;
		spotRadius?: number;
		cursorWidth?: number;
		onmousemove?: (event: MouseEvent, datapoint: { index: number; value: number }) => void;
		onmouseout?: (event: MouseEvent) => void;
	}

	export default function sparkline(
		svg: SVGSVGElement,
		values: number[],
		options?: SparklineOptions
	): void;
}
